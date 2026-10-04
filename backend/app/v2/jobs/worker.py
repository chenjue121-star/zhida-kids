"""Durable recognition worker. Run separately: python -m app.v2.jobs.worker."""
from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid4
from sqlalchemy import select, or_, and_
from app.v2.core.clock import utcnow
from app.v2.core.errors import DomainError
from app.v2.families.access import family_access
from app.v2.identity.models import User
from app.v2.media.models import MediaAsset
from app.v2.recognition.models import IntakeBatch, IntakeItem, RecognitionAttempt, Candidate
from app.v2.recognition.normalize import normalize_result
from app.v2.recognition.operations import digest
from app.v2.integrations.recognition import RecognitionFailure, UnconfiguredProvider


@dataclass(frozen=True)
class Claim:
    attempt_id: int
    token: str
    family_id: int
    batch_id: int
    item_id: int
    generation: int
    object_key: str
    content_type: str


def provider_from_settings(settings):
    if settings.recognition_provider == 'qwen' and settings.qwen_api_key.get_secret_value():
        from app.v2.integrations.qwen import QwenProvider
        return QwenProvider(settings.qwen_api_key.get_secret_value(), settings.recognition_model, settings.qwen_base_url)
    if settings.recognition_provider == 'ark' and settings.ark_api_key.get_secret_value():
        from app.v2.integrations.ark import ArkProvider
        return ArkProvider(settings.ark_api_key.get_secret_value(), settings.recognition_model, settings.ark_base_url)
    return UnconfiguredProvider()


class RecognitionWorker:
    def __init__(self, session_factory, storage, provider, clock=utcnow, lease_seconds=120, max_tries=3):
        self.sessions, self.storage, self.provider = session_factory, storage, provider
        self.clock, self.lease_seconds, self.max_tries = clock, lease_seconds, max_tries

    def _locked(self, db, attempt_id):
        # Discover identity without locking, then follow the common family-first order.
        row = db.execute(select(RecognitionAttempt.item_id, IntakeItem.batch_id, IntakeBatch.family_id,
            IntakeBatch.created_by).join(IntakeItem, IntakeItem.id == RecognitionAttempt.item_id)
            .join(IntakeBatch, IntakeBatch.id == IntakeItem.batch_id).where(RecognitionAttempt.id == attempt_id)).first()
        if row is None:
            return None
        item_id, batch_id, family_id, creator_id = row
        user = db.get(User, creator_id)
        permission = True
        try:
            family_access(db, family_id, user, ('admin', 'editor'), lock=True)
        except DomainError:
            permission = False
        batch = db.scalar(select(IntakeBatch).where(IntakeBatch.id == batch_id).with_for_update()
                          .execution_options(populate_existing=True))
        item = db.scalar(select(IntakeItem).where(IntakeItem.id == item_id).with_for_update()
                         .execution_options(populate_existing=True))
        attempt = db.scalar(select(RecognitionAttempt).where(RecognitionAttempt.id == attempt_id).with_for_update()
                            .execution_options(populate_existing=True))
        return batch, item, attempt, permission

    def _terminal(self, item, attempt, status, code, message):
        attempt.status = status
        attempt.error = {'code': code, 'message': message}
        attempt.claim_token, attempt.lease_until = None, None
        if item.generation == attempt.generation:
            item.status, item.error = status, attempt.error
            item.version += 1

    def claim(self):
        now = self.clock()
        with self.sessions() as db:
            ids = list(db.scalars(select(RecognitionAttempt.id).where(or_(
                and_(RecognitionAttempt.status == 'queued', RecognitionAttempt.available_at <= now),
                and_(RecognitionAttempt.status == 'running', RecognitionAttempt.lease_until <= now)))
                .order_by(RecognitionAttempt.id).limit(30)))
        for attempt_id in ids:
            with self.sessions() as db:
                locked = self._locked(db, attempt_id)
                if locked is None:
                    continue
                batch, item, attempt, permission = locked
                if attempt.status == 'running' and attempt.lease_until <= now:
                    self._terminal(item, attempt, 'uncertain', 'RECOGNITION_UNCERTAIN', '识别进程中断，结果未确定，请继续手填')
                    db.commit()
                    continue
                if attempt.status != 'queued' or attempt.available_at > now:
                    continue
                if not permission:
                    self._terminal(item, attempt, 'failed', 'PERMISSION_REVOKED', '录入权限已失效')
                    db.commit()
                    continue
                if item.discarded or item.generation != attempt.generation:
                    self._terminal(item, attempt, 'failed', 'CANDIDATE_DISCARDED', '照片已放弃或已被后续识别替代')
                    db.commit()
                    continue
                asset = db.get(MediaAsset, item.asset_id)
                if asset is None:
                    self._terminal(item, attempt, 'failed', 'IMAGE_UNAVAILABLE', '原图暂不可用，请继续手填')
                    db.commit()
                    continue
                attempt.status, attempt.claim_token = 'running', uuid4().hex
                attempt.lease_until = now + timedelta(seconds=self.lease_seconds)
                attempt.tries += 1
                item.status, item.error = 'running', None
                item.version += 1
                claim = Claim(attempt.id, attempt.claim_token, batch.family_id, batch.id, item.id,
                              attempt.generation, asset.object_key, asset.content_type)
                db.commit()
                return claim
        return None

    def _live(self, item, attempt, claim):
        return attempt.status == 'running' and attempt.claim_token == claim.token and item.generation == claim.generation

    def _authorized(self, claim):
        with self.sessions() as db:
            locked = self._locked(db, claim.attempt_id)
            if locked is None:
                return False
            _, item, attempt, permission = locked
            if not self._live(item, attempt, claim):
                return False
            if attempt.lease_until <= self.clock():
                self._terminal(item, attempt, 'uncertain', 'RECOGNITION_UNCERTAIN', '识别租约已失效，请继续手填')
            elif not permission or item.discarded:
                self._terminal(item, attempt, 'failed', 'PERMISSION_REVOKED' if not permission else 'CANDIDATE_DISCARDED',
                               '录入权限已失效' if not permission else '照片已明确放弃')
            else:
                return True
            db.commit()
            return False

    def process(self, claim):
        if not self._authorized(claim):
            return
        try:
            image = self.storage.get(claim.object_key)
        except (DomainError, OSError, ValueError):
            self.publish(claim, error=RecognitionFailure('IMAGE_UNAVAILABLE', '原图暂不可用，请继续手填'))
            return
        try:
            # No SQL session or family lock is held during this provider request.
            result = self.provider.recognize(image, claim.content_type)
            self.publish(claim, result)
        except RecognitionFailure as error:
            self.publish(claim, error=error)
        except Exception:
            # Unknown exceptions can follow an outbound request: never blindly rebill.
            self.publish(claim, error=RecognitionFailure('RECOGNITION_UNCERTAIN', '识别结果未确定，请继续手填', uncertain=True))

    def publish(self, claim, result=None, error=None):
        now = self.clock()
        with self.sessions() as db:
            locked = self._locked(db, claim.attempt_id)
            if locked is None:
                return False
            batch, item, attempt, permission = locked
            if not self._live(item, attempt, claim):
                return False
            if attempt.lease_until <= now:
                self._terminal(item, attempt, 'uncertain', 'RECOGNITION_UNCERTAIN', '识别租约已失效，请继续手填')
                db.commit()
                return False
            if not permission or item.discarded:
                self._terminal(item, attempt, 'failed', 'PERMISSION_REVOKED' if not permission else 'CANDIDATE_DISCARDED',
                               '录入权限已失效' if not permission else '照片已明确放弃')
                db.commit()
                return False
            if error is None:
                try:
                    normalized = normalize_result(result)
                except RecognitionFailure as invalid:
                    error = invalid
            if error is not None:
                if error.uncertain:
                    self._terminal(item, attempt, 'uncertain', error.code, error.message)
                elif error.retryable and attempt.tries < self.max_tries:
                    attempt.status = 'queued'
                    attempt.error = {'code': error.code, 'message': error.message}
                    attempt.claim_token, attempt.lease_until = None, None
                    attempt.available_at = now + timedelta(seconds=2 ** attempt.tries)
                    item.status, item.error = 'queued', attempt.error
                    item.version += 1
                else:
                    self._terminal(item, attempt, 'failed', error.code, error.message)
                db.commit()
                return True
            existing = list(db.scalars(select(Candidate).where(Candidate.item_id == item.id).with_for_update()))
            preselect = (item.source == 'camera' and attempt.generation == 1 and attempt.tries == 1 and not existing and len(normalized) == 1
                         and normalized[0]['category'] is not None and normalized[0]['bbox'] is not None)
            for index, fields in enumerate(normalized):
                client_id = 'recognition:' + str(attempt.id) + ':' + str(index)
                db.add(Candidate(batch_id=batch.id, item_id=item.id, attempt_id=attempt.id,
                    client_id=client_id, request_hash=digest(fields), owners=[{'child_id': batch.default_child_id, 'fit': 'fit'}],
                    selected=preselect, dirty_fields=[], **fields))
            from app.v2.recognition.trace import recognition_trace
            attempt.result = {'candidates': normalized, 'trace': recognition_trace(result, self.provider)}
            attempt.status, attempt.error = 'succeeded', None
            attempt.claim_token, attempt.lease_until = None, None
            item.status, item.error = 'succeeded', None
            item.version += 1
            batch.version += 1
            db.commit()
            return True

    def run_once(self):
        claim = self.claim()
        if claim is None:
            return False
        self.process(claim)
        return True


def main():
    import argparse
    import time
    from app.v2.core.config import V2Settings
    from app.v2.core.database import build_engine, load_metadata, session_factory
    from app.v2.media.storage import FileStorage
    parser = argparse.ArgumentParser(description='Private, durable v2 recognition worker')
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    settings = V2Settings()
    load_metadata()
    engine = build_engine(settings.database_url)
    worker = RecognitionWorker(session_factory(engine), FileStorage(settings.private_storage_dir),
        provider_from_settings(settings), lease_seconds=settings.recognition_lease_seconds,
        max_tries=settings.recognition_max_attempts)
    try:
        while True:
            worked = worker.run_once()
            if args.once:
                break
            if not worked:
                time.sleep(1)
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
