from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Category = Literal['top', 'bottom', 'outerwear', 'dress', 'onesie', 'shoes', 'accessory']
Pattern = Literal['solid', 'stripe', 'plaid', 'print', 'dots', 'unknown']
Thickness = Literal['thin', 'medium', 'thick', 'unknown']
State = Literal['ready', 'washing', 'missing']
Fit = Literal['small', 'fit', 'large', 'unknown']
Color = Literal['black', 'white', 'gray', 'red', 'orange', 'yellow', 'green', 'blue', 'purple',
                'pink', 'brown', 'beige', 'multicolor', 'unknown']


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class Owner(Input):
    child_id: int = Field(gt=0)
    fit: Fit


class Version(Input):
    expected_version: int = Field(ge=1)


class GarmentPatch(Version):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    category: Category | None = None
    colors: list[Color] | None = Field(default=None, min_length=1, max_length=15)
    pattern: Pattern | None = None
    thickness: Thickness | None = None
    state: State | None = None

    @model_validator(mode='after')
    def no_null_updates(self):
        if any(getattr(self, key) is None for key in self.model_fields_set - {'expected_version'}):
            raise ValueError('更新字段不能为 null')
        return self


class OwnersPatch(Version):
    owners: list[Owner] = Field(min_length=1, max_length=50)


class Transfer(Version):
    child_id: int = Field(gt=0)
    fit: Fit


class Archive(Version):
    operation_id: str = Field(min_length=1, max_length=128)


class Restore(OwnersPatch):
    operation_id: str = Field(min_length=1, max_length=128)


class BulkItem(Version):
    id: int = Field(gt=0)


class Bulk(Input):
    operation_id: str = Field(min_length=1, max_length=128)
    action: Literal['state', 'archive']
    state: State | None = None
    items: list[BulkItem] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def valid_selection(self):
        if self.action == 'state' and self.state is None:
            raise ValueError('请选择目标状态')
        if len({item.id for item in self.items}) != len(self.items):
            raise ValueError('同一实物只能选择一次')
        return self
