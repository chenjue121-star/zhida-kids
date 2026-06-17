from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class WechatLoginIn(BaseModel):
    code: str = Field(min_length=1)
    nickname: Optional[str] = None
    avatar: Optional[str] = None


class UserOut(BaseModel):
    id: int
    nickname: str
    avatar: str
    role: str
    city: str
    style_preference: List[str]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LoginOut(BaseModel):
    token: str
    user: UserOut
    onboarding_complete: bool


class UserProfileUpdate(BaseModel):
    role: str = ""
    city: str = ""
    style_preference: List[str] = Field(default_factory=list)


class ChildBase(BaseModel):
    nickname: str = Field(min_length=1, max_length=80)
    gender: str = Field(pattern="^(boy|girl)$")
    birthday: date
    height: float = Field(gt=0)
    weight: Optional[float] = Field(default=None, ge=0)
    skin_tone: str = ""
    photo_url: str = ""
    avatar_url: str = ""


class ChildCreate(ChildBase):
    pass


class ChildUpdate(BaseModel):
    nickname: Optional[str] = Field(default=None, min_length=1, max_length=80)
    gender: Optional[str] = Field(default=None, pattern="^(boy|girl)$")
    birthday: Optional[date] = None
    height: Optional[float] = Field(default=None, gt=0)
    weight: Optional[float] = Field(default=None, ge=0)
    skin_tone: Optional[str] = None
    photo_url: Optional[str] = None
    avatar_url: Optional[str] = None


class ChildOut(ChildBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChildAvatarGenerateOut(BaseModel):
    avatar_url: str = ""
    prompt: str = ""
    status: str = "mock"
    message: str = ""


class ClothingBase(BaseModel):
    child_id: int
    photo_url: str = ""
    type: str = Field(min_length=1, max_length=40)
    sub_type: str = ""
    main_color: str = Field(min_length=1, max_length=40)
    pattern: str = "solid"
    season: List[str] = Field(default_factory=list)
    thickness: str = Field(min_length=1, max_length=40)
    style_tags: List[str] = Field(default_factory=list)
    brand: str = ""
    size: str = ""
    status: str = "active"


class ClothingCreate(ClothingBase):
    pass


class ClothingUpdate(BaseModel):
    photo_url: Optional[str] = None
    type: Optional[str] = Field(default=None, min_length=1, max_length=40)
    sub_type: Optional[str] = None
    main_color: Optional[str] = Field(default=None, min_length=1, max_length=40)
    pattern: Optional[str] = None
    season: Optional[List[str]] = None
    thickness: Optional[str] = Field(default=None, min_length=1, max_length=40)
    style_tags: Optional[List[str]] = None
    brand: Optional[str] = None
    size: Optional[str] = None
    status: Optional[str] = None
    wear_count: Optional[int] = Field(default=None, ge=0)
    last_worn_at: Optional[datetime] = None


class ClothingOut(ClothingBase):
    id: int
    wear_count: int
    last_worn_at: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ClothingRecognizeIn(BaseModel):
    photo_url: str = Field(min_length=1)


class ClothingRecognizeOut(BaseModel):
    type: str = ""
    sub_type: str = ""
    main_color: str = ""
    pattern: str = ""
    season: List[str] = Field(default_factory=list)
    thickness: str = ""
    style_tags: List[str] = Field(default_factory=list)
    brand: str = ""
    size: str = ""
    confidence: float = Field(default=0, ge=0, le=1)
    notes: str = ""
    cutout_url: str = ""


class ClothingUploadAndRecognizeOut(BaseModel):
    photo_url: str = ""
    cutout_url: str = ""
    recognition: ClothingRecognizeOut


class DiaryBase(BaseModel):
    child_id: int
    date: date
    clothing_ids: List[int] = Field(default_factory=list)
    scene: str = ""
    reason: str = ""
    note: str = ""
    mood: str = ""
    rating: int = Field(default=0, ge=0, le=5)
    actual_photo_url: str = ""


class DiaryCreate(DiaryBase):
    pass


class DiaryUpdate(BaseModel):
    clothing_ids: Optional[List[int]] = None
    scene: Optional[str] = None
    reason: Optional[str] = None
    note: Optional[str] = None
    mood: Optional[str] = None
    rating: Optional[int] = Field(default=None, ge=0, le=5)
    actual_photo_url: Optional[str] = None


class DiaryOut(DiaryBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UploadOut(BaseModel):
    url: str
    filename: str
    reused: bool = False


class WeatherOut(BaseModel):
    city: str
    temp: int
    weather: str
    humidity: int
    suggestion: str


class WeatherSnapshot(BaseModel):
    city: str = ""
    temp: int = 25
    weather: str = ""
    humidity: int = 0
    suggestion: str = ""


class OutfitRecommendIn(BaseModel):
    child_id: int
    scene: str = "school"
    weather: Optional[WeatherSnapshot] = None
    exclude_clothing_ids: List[int] = Field(default_factory=list)
    locked_clothing_ids: List[int] = Field(default_factory=list)
    replace_group: str = ""


class OutfitRecommendOut(BaseModel):
    items: List[ClothingOut] = Field(default_factory=list)
    reason: str = ""
    tips: str = ""
    scene: str = ""
    date: date
    weather: Optional[WeatherSnapshot] = None
    source: str = "fallback"
    warnings: List[str] = Field(default_factory=list)
    style_profile: str = ""
    ruleset_id: str = ""
    ruleset_version: str = ""
    cached: bool = False
