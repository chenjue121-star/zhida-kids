from datetime import date
from typing import Literal
from pydantic import Field, model_validator, field_validator
from app.v2.families.schemas import Input

Scene = Literal['daily', 'outdoor', 'school', 'formal', 'sport']
Mode = Literal['family', 'current_member', 'designated_member']


class Common(Input):
    child_id: int = Field(gt=0, le=9223372036854775807)
    target_date: date
    scene: Scene = 'daily'
    preference_mode: Mode = 'family'
    designated_member_id: int | None = Field(None, gt=0, le=9223372036854775807)
    city: str | None = Field(None, min_length=1, max_length=120)
    lat: float | None = Field(None, ge=-90, le=90, allow_inf_nan=False)
    lon: float | None = Field(None, ge=-180, le=180, allow_inf_nan=False)

    @model_validator(mode='after')
    def valid_basis(self):
        if (self.lat is None) != (self.lon is None):
            raise ValueError('Latitude and longitude are required together')
        if (self.preference_mode == 'designated_member') != (self.designated_member_id is not None):
            raise ValueError('Only designated_member requires a membership id')
        return self


class Constraints(Common):
    draft_id: str = Field(min_length=1, max_length=128)
    locked_ids: list[int] = Field(default_factory=list, max_length=50)
    excluded_ids: list[int] = Field(default_factory=list, max_length=100)

    @field_validator('locked_ids', 'excluded_ids')
    @classmethod
    def distinct_ids(cls, values):
        if any(v <= 0 or v > 9223372036854775807 for v in values) or len(set(values)) != len(values):
            raise ValueError('Garment ids must be distinct positive ids')
        return values


class Item(Input):
    garment_id: int = Field(gt=0, le=9223372036854775807)
    expected_version: int = Field(ge=1)
    replaces_garment_id: int | None = Field(None, gt=0, le=9223372036854775807)


class Backup(Input):
    mode: Literal['none', 'partial', 'full'] = 'none'
    items: list[Item] = Field(default_factory=list, max_length=50)

    @model_validator(mode='after')
    def no_unselected_items(self):
        if self.mode == 'none' and self.items:
            raise ValueError('Unselected backup cannot contain items')
        return self


class Draft(Constraints):
    action_id: str | None = Field(None, min_length=1, max_length=128)
    main_items: list[Item] = Field(default_factory=list, max_length=50)
    backup: Backup = Field(default_factory=Backup)
    target_plan_id: int | None = Field(None, gt=0, le=9223372036854775807)
    expected_version: int | None = Field(None, ge=1)
    recommendation_id: int | None = Field(None, gt=0, le=9223372036854775807)
    sharing_grants: list[dict] = Field(default_factory=list, max_length=50)
    weather_acknowledged: bool = False
    backup_needs_review: bool = False

    @model_validator(mode='after')
    def target_version(self):
        if (self.target_plan_id is not None) != (self.expected_version is not None):
            raise ValueError('Only editing a plan requires expected_version')
        for items in (self.main_items, self.backup.items):
            if len({i.garment_id for i in items}) != len(items):
                raise ValueError('Each physical item can only occur once per usage')
        return self


class Recommend(Draft):
    request_id: str = Field(min_length=1, max_length=128)
    exclude_combination: list[int] = Field(default_factory=list, max_length=50)


class Candidates(Draft):
    replace_id: int = Field(gt=0, le=9223372036854775807)
    usage: Literal['main', 'backup'] = 'main'


class BackupRequest(Draft):
    mode: Literal['partial', 'full']


class Period(Input):
    child_id: int = Field(gt=0, le=9223372036854775807)
    start: str = Field(pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    end: str = Field(pattern=r'^([01]\d|2[0-3]):[0-5]\d$')


class Sharing(Draft):
    garment_id: int = Field(gt=0, le=9223372036854775807)
    reason: str = Field(min_length=1, max_length=500)
    periods: list[Period] = Field(min_length=2, max_length=50)


class Save(Draft):
    input_version: str = Field(min_length=64, max_length=64)
    operation_id: str = Field(min_length=1, max_length=128)


class Cancel(Input):
    expected_version: int = Field(ge=1)
    operation_id: str = Field(min_length=1, max_length=128, pattern=r'^\S+$')


class Reuse(Input):
    expected_source_version: int = Field(ge=1)
    child_id: int = Field(gt=0, le=9223372036854775807)
    target_date: date
    scene: Scene | None = None
    draft_id: str = Field(min_length=1, max_length=128, pattern=r'^\S+$')
    preference_mode: Mode = 'family'
    designated_member_id: int | None = Field(None, gt=0, le=9223372036854775807)

    @model_validator(mode='after')
    def valid_basis(self):
        if (self.preference_mode == 'designated_member') != (self.designated_member_id is not None):
            raise ValueError('Only designated_member requires a membership id')
        return self
