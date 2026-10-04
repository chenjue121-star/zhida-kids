from typing import Literal
from pydantic import Field, model_validator
from app.v2.wardrobe.schemas import Input, Owner, Category, Color, Pattern, Thickness, State, Version


class BatchCreate(Input):
    default_child_id: int = Field(gt=0)


class ItemCreate(Input):
    client_id: str = Field(min_length=1, max_length=128)
    source: Literal['camera', 'album', 'manual']


class CandidateCreate(Input):
    item_id: int = Field(gt=0)
    client_id: str = Field(min_length=1, max_length=128)
    name: str = Field(default='', max_length=80)
    category: Category | None = None
    colors: list[Color] = Field(default_factory=lambda: ['unknown'], min_length=1, max_length=15)
    pattern: Pattern = 'unknown'
    thickness: Thickness = 'unknown'
    owners: list[Owner] | None = Field(default=None, max_length=50)
    state: State = 'ready'
    selected: bool = False


class CandidatePatch(Version):
    name: str | None = Field(default=None, max_length=80)
    category: Category | None = None
    colors: list[Color] | None = Field(default=None, min_length=1, max_length=15)
    pattern: Pattern | None = None
    thickness: Thickness | None = None
    owners: list[Owner] | None = Field(default=None, min_length=1, max_length=50)
    state: State | None = None
    selected: bool | None = None
    discarded: bool | None = None
    ownership_exception: bool | None = None

    @model_validator(mode='after')
    def no_null_updates(self):
        if any(getattr(self, key) is None for key in self.model_fields_set - {'category', 'expected_version'}):
            raise ValueError('此字段不能为 null')
        return self


class Entry(Input):
    candidate_id: int = Field(gt=0)
    expected_version: int = Field(ge=1)
    action: Literal['new', 'existing']
    existing_garment_id: int | None = Field(default=None, gt=0)
    expected_garment_version: int | None = Field(default=None, ge=1)

    @model_validator(mode='after')
    def target_required(self):
        if self.action == 'existing' and (self.existing_garment_id is None or self.expected_garment_version is None):
            raise ValueError('使用已有实物须提供 ID 和版本')
        return self


class Confirmation(Input):
    operation_id: str = Field(min_length=1, max_length=128)
    entries: list[Entry] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def unique_candidates(self):
        if len({entry.candidate_id for entry in self.entries}) != len(self.entries):
            raise ValueError('同一候选只能确认一次')
        return self


class ItemPatch(Version):
    discarded: Literal[True]
