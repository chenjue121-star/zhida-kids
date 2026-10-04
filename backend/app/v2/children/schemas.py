from __future__ import annotations

from datetime import date
from typing import Literal, Optional
from pydantic import Field, model_validator
from app.v2.families.schemas import Input
from app.v2.preferences.schemas import InitialPreferences

SkinTone = Literal['light', 'medium', 'deep']


class MeasurementCreate(Input):
    height_cm: Optional[float] = Field(default=None, gt=0, le=999999.99, allow_inf_nan=False)
    weight_kg: Optional[float] = Field(default=None, gt=0, le=999999.99, allow_inf_nan=False)
    measured_on: date

    @model_validator(mode='after')
    def has_measurement(self):
        if self.height_cm is None and self.weight_kg is None:
            raise ValueError('At least one measurement is required')
        for value in (self.height_cm, self.weight_kg):
            if value is not None and round(value, 2) <= 0:
                raise ValueError('Measurement must remain positive at two decimal places')
        return self


class ChildCreate(Input):
    nickname: str = Field(min_length=1, max_length=80)
    birthday: Optional[date] = None
    age_months: Optional[int] = Field(default=None, ge=0, le=83)
    skin_tone: Optional[SkinTone] = None
    measurement: Optional[MeasurementCreate] = None
    preferences: InitialPreferences = Field(default_factory=InitialPreferences)

    @model_validator(mode='after')
    def age_or_birthday(self):
        if (self.birthday is None) == (self.age_months is None):
            raise ValueError('Choose either birthday or age in months')
        return self


class ChildPatch(Input):
    expected_version: int = Field(ge=1)
    nickname: Optional[str] = Field(default=None, min_length=1, max_length=80)
    birthday: Optional[date] = None
    age_months: Optional[int] = Field(default=None, ge=0, le=83)
    skin_tone: Optional[SkinTone] = None

    @model_validator(mode='after')
    def required_values(self):
        for name in ('nickname', 'birthday'):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(name + ' cannot be null')
        if 'age_months' in self.model_fields_set and self.age_months is None:
            raise ValueError('age_months cannot be null')
        if 'birthday' in self.model_fields_set and 'age_months' in self.model_fields_set:
            raise ValueError('Choose either birthday or age in months')
        return self
