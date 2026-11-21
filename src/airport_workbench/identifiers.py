"""Pydantic identifier contracts for the workbench HTTP API."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from airport_surface import EdgeId, EdgeKey, NodeId
from airport_surface.identifiers import NODE_ID_PATTERN

type NodeIdField = Annotated[NodeId, StringConstraints(pattern=NODE_ID_PATTERN)]
type EdgeKeyField = Annotated[EdgeKey, Field(strict=True, ge=0)]


class EdgeIdentity(BaseModel):
    """The stable identity of one MultiGraph edge."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    u: NodeIdField
    v: NodeIdField
    key: EdgeKeyField

    def as_tuple(self) -> EdgeId:
        return self.u, self.v, self.key
