from __future__ import annotations

from typing import Literal, Optional
from pydantic import Field, model_validator, field_validator
from app.v2.families.schemas import Input

Style = Literal['clean_daily', 'sporty', 'soft_natural', 'playful_print']
Mode = Literal['family', 'designated_member', 'current_member']
Thermal = Literal['unknown', 'neutral', 'runs_warm', 'runs_cold']
Fit = Literal['unknown', 'regular', 'loose']


class InitialPreferences(Input):
    styles: list[Style] = Field(default_factory=list, max_length=4)
    mode: Mode = 'family'
    designated_member_id: Optional[int] = Field(default=None, gt=0, le=9223372036854775807)
    thermal_preference: Thermal = 'unknown'
    fit_preference: Fit = 'unknown'
    avoid_high_neck: Optional[bool] = None

    @model_validator(mode='after')
    def valid_mode(self):
        if (self.mode == 'designated_member') != (self.designated_member_id is not None):
            raise ValueError('Only designated_member mode requires designated_member_id')
        if len(set(self.styles)) != len(self.styles):
            raise ValueError('Styles must be unique')
        return self


class SettingsPatch(Input):
    expected_version: int = Field(ge=1)
    mode: Optional[Mode] = None
    designated_member_id: Optional[int] = Field(default=None, gt=0, le=9223372036854775807)
    thermal_preference: Optional[Thermal] = None
    fit_preference: Optional[Fit] = None
    avoid_high_neck: Optional[bool] = None

    @model_validator(mode='after')
    def required_values(self):
        for name in ('mode', 'thermal_preference', 'fit_preference'):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(name + ' cannot be null')
        return self


class ProfilePut(Input):
    expected_version: int = Field(ge=0)
    styles: list[Style] = Field(max_length=4)

    @field_validator('styles')
    @classmethod
    def unique_styles(cls, value):
        if len(set(value)) != len(value):
            raise ValueError('Styles must be unique')
        return value


class Feedback(Input):
    event_id: str = Field(min_length=1, max_length=128, pattern=r'^\S+$')
    plan_id: int = Field(gt=0, le=9223372036854775807)
    plan_version: int = Field(ge=1)
    signal: Literal['like', 'dislike']
    reason: Literal['aesthetic', 'comfort', 'washing', 'missing', 'too_small', 'skip']
    styles: list[Style] = Field(default_factory=list, max_length=4)

    @field_validator('styles')
    @classmethod
    def unique_styles(cls, value):
        if len(set(value)) != len(value):
            raise ValueError('Styles must be unique')
        return value


class TagAction(Input):
    expected_version: int = Field(ge=0)
    action: Literal['accept', 'dismiss']
