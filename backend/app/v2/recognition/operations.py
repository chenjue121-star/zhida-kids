from hashlib import sha256
import json
from sqlalchemy import select
from app.v2.core.errors import fail
from app.v2.recognition.models import Operation


def digest(payload):
    return sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()


def lookup(db, family_id, actor_id, scope, operation_id):
    return db.scalar(select(Operation).where(Operation.family_id == family_id, Operation.actor_id == actor_id,
        Operation.scope == scope, Operation.operation_id == operation_id).with_for_update())


def run_operation(db, family, user, scope, operation_id, payload, execute):
    # The family lock is held; all item savepoints and this receipt commit together.
    previous = lookup(db, family.id, user.id, scope, operation_id)
    request_hash = digest(payload)
    if previous is not None:
        if previous.request_hash != request_hash:
            fail(409, 'IDEMPOTENCY_CONFLICT', '该操作标识已用于不同内容，请查询原操作')
        return previous.response
    if db.get_bind().dialect.name == 'sqlite':
        # sqlite3's legacy mode does not BEGIN on SELECT. Without this, the
        # first SAVEPOINT becomes an outer transaction and RELEASE commits it
        # before the operation receipt exists, defeating an outer rollback.
        connection = db.connection()
        if not connection.connection.driver_connection.in_transaction:
            connection.exec_driver_sql('BEGIN')
    response = execute()
    db.add(Operation(family_id=family.id, actor_id=user.id, scope=scope, operation_id=operation_id,
                     request_hash=request_hash, response=response))
    db.flush()
    return response


def unknown(operation_id):
    return {'operation_id': operation_id, 'status': 'unknown', 'results': [],
            'counts': {'new': 0, 'existing': 0, 'failed': 0}}


def operation_response(operation_id, results):
    return {'operation_id': operation_id, 'status': 'completed', 'results': results,
            'counts': {'new': sum(r['status'] == 'success' and r['kind'] == 'new' for r in results),
                       'existing': sum(r['status'] == 'success' and r['kind'] == 'existing' for r in results),
                       'failed': sum(r['status'] == 'failed' for r in results)}}


def not_executed(operation_id, entries, id_key='candidate_id'):
    return operation_response(operation_id, [{id_key: str(entry[id_key]), 'status': 'failed',
        'kind': entry.get('action', 'existing') if id_key == 'candidate_id' else 'existing', 'garment': None,
        'error': {'code': 'NOT_EXECUTED', 'message': '已核实该操作未执行，可重新核对后提交'}} for entry in entries])
