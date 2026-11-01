"""Stable, lossless identifiers used by the workbench HTTP API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator


class EncodedValue(BaseModel):
    """An integer or string graph identifier without JavaScript number coercion."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["int", "str"]
    value: str

    @field_validator("value")
    @classmethod
    def validate_value(cls, value: str, info: Any) -> str:
        if info.data.get("type") == "int":
            if not value or value.strip() != value or value in {"+", "-"}:
                raise ValueError("整数 ID 必须是规范的十进制字符串")
            try:
                decoded = int(value, 10)
            except ValueError as error:
                raise ValueError("整数 ID 必须是规范的十进制字符串") from error
            if str(decoded) != value:
                raise ValueError("整数 ID 必须是规范的十进制字符串")
        return value


class EdgeIdentity(BaseModel):
    """The stable identity of one MultiGraph edge."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    u: EncodedValue
    v: EncodedValue
    key: EncodedValue


def encode_value(value: Any) -> dict[str, str]:
    if isinstance(value, bool):
        raise TypeError("布尔值不是受支持的图对象 ID")
    if isinstance(value, int):
        return {"type": "int", "value": str(value)}
    if isinstance(value, str):
        return {"type": "str", "value": value}
    raise TypeError(f"不支持的图对象 ID 类型: {type(value).__qualname__}")


def decode_value(value: EncodedValue) -> int | str:
    if value.type == "str":
        return value.value
    text = value.value
    if not text or text.strip() != text or text in {"+", "-"}:
        raise ValueError("整数 ID 必须是规范的十进制字符串")
    try:
        decoded = int(text, 10)
    except ValueError as error:
        raise ValueError("整数 ID 必须是规范的十进制字符串") from error
    if str(decoded) != text:
        raise ValueError("整数 ID 必须是规范的十进制字符串")
    return decoded


def encode_edge(u: Any, v: Any, key: Any) -> dict[str, dict[str, str]]:
    return {"u": encode_value(u), "v": encode_value(v), "key": encode_value(key)}


def decode_edge(identity: EdgeIdentity) -> tuple[int | str, int | str, int | str]:
    return decode_value(identity.u), decode_value(identity.v), decode_value(identity.key)
