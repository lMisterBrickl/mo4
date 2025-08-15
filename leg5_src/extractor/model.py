from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional, Union, List


class MetaInfo(BaseModel):
    cui: Optional[str] = None
    legal_type: Optional[str] = None
    reg_number: Optional[str] = None
    euid: Optional[str] = None
    caen: List[str] = []
    capital: Optional[str] = None
    address: Optional[str] = None


class Entry(BaseModel):
    type: Optional[str] = None
    number: Optional[str] = None
    date: Optional[str] = None
    year: Optional[str] = None
    company_name: Optional[str] = None
    meta: MetaInfo = Field(default_factory=MetaInfo)
    raw_text: str = ""
    bulletin_id: Optional[str] = None
    article_id: Optional[str] = None
    list_parent_classes: Optional[str] = None
    collapse_id: Optional[str] = None
    source_href: Optional[str] = None
