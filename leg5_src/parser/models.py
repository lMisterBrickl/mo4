from __future__ import annotations
from pydantic import BaseModel


class Address(BaseModel):
    fullAddress: str = None
    country: str = None
    county: str = None
    city: str = None


class Associate(BaseModel):
    name: str = None
    birth_date: str = None
    startDate: str = None
    endDate: str = None
    address: str = None
    place_of_birth: str = None
    citizenship: str = None
    type_ID: str = None
    series_ID: str = None
    number_ID: str = None
    cnp: str = None
    percentage_ownership: str = None


class MainInfo(BaseModel):
    addresses: list = []
    caen: list = []
    cui: str = None
    dateOfCreation: str = None
    euid: str = None
    capital: str = None
    ownership: list = []
    activityFieldDescription: str = None
    fieldOfActivity: str = None
    country: str = None
    dataSource: list = []
    otherName: str = None
    registrationNumber: str = None


class CompanyModel(BaseModel):
    id: str = None
    type: str = None
    name: str = None
    mainInfo: MainInfo = None
