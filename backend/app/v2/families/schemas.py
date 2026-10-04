from __future__ import annotations

from typing import Literal, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class FamilyCreate(Input):
    name: str = Field(min_length=1, max_length=80)
    city: Optional[str] = Field(default=None, min_length=1, max_length=120)
    timezone: str = Field(default='Asia/Shanghai', max_length=64)

    @field_validator('timezone')
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError('Unknown timezone')
        return value


class FamilyPatch(Input):
    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    city: Optional[str] = Field(default=None, min_length=1, max_length=120)
    timezone: Optional[str] = Field(default=None, max_length=64)
    expected_version: int = Field(ge=1)

    @model_validator(mode='after')
    def valid_fields(self):
        for field in ('name', 'timezone'):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(field + ' cannot be null')
        if self.timezone is not None:
            FamilyCreate.valid_timezone(self.timezone)
        return self


class InvitationCreate(Input):
    role: Literal['editor', 'viewer'] = 'editor'


class InvitationToken(Input):
    token: str = Field(min_length=1, max_length=256)


class MemberPatch(Input):
    role: Literal['admin', 'editor', 'viewer']
    expected_family_version: int = Field(ge=1)
