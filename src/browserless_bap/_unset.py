"""Sentinel separating an omitted GraphQL argument from an explicit null."""

from enum import Enum


class UnsetType(Enum):
    UNSET = "<UNSET>"


UNSET = UnsetType.UNSET

__all__ = ["UNSET", "UnsetType"]
