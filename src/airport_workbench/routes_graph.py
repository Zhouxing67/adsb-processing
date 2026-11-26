"""HTTP routes for interactive airport graph editing."""

from __future__ import annotations

from pathlib import Path as FilePath
from typing import Any, Callable

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, StrictInt
from shapely.geometry import mapping

from utils.json_value import to_json_value

from .api_models import (
    DeleteEdgePreviewResponse,
    DeleteNodePreviewResponse,
    GraphCommandResponse,
    ManualSnapPreviewResponse,
    MergeCandidatesResponse,
    MergeNodesPreviewResponse,
    RestoreOptionsResponse,
    SplitSourcePreviewResponse,
)
from .editor import EditorSession
from .identifiers import EdgeIdentity, NodeIdField


class VersionedRequest(BaseModel):
    expected_revision: StrictInt


class DrawConnectionRequest(VersionedRequest):
    start: NodeIdField
    end: NodeIdField
    intermediate_points: list[tuple[float, float]] = Field(default_factory=list, max_length=10000)
    aeroway: str = "taxiway"
    ref: str | None = None


class RestoreRequest(VersionedRequest):
    start: NodeIdField
    end: NodeIdField
    candidate_id: str | None = None


class MergeNodesRequest(VersionedRequest):
    node_ids: list[NodeIdField] = Field(default_factory=list)
    canonical_node_id: NodeIdField | None = None


class UpdatedNodeAttributes(VersionedRequest):
    node: NodeIdField
    attributes: dict[str, Any]


class UpdatedEdgeAttributes(VersionedRequest):
    edge: EdgeIdentity
    attributes: dict[str, Any]


class EdgeRequest(VersionedRequest):
    edge: EdgeIdentity


class NodeDeletionRequest(VersionedRequest):
    node: NodeIdField
    pair_ids: list[str] = Field(default_factory=list)
    discard_unpaired: bool = False


class SourceSplitRequest(VersionedRequest):
    edge: EdgeIdentity
    longitude: float
    latitude: float
    osm_node_id: NodeIdField | None = None


class ManualSnapRequest(VersionedRequest):
    node: NodeIdField
    edge: EdgeIdentity


class CreateStandClusterRequest(VersionedRequest):
    edges: list[EdgeIdentity] = Field(min_length=1)
    name: str | None = None


class AssignStandClusterRequest(VersionedRequest):
    edges: list[EdgeIdentity] = Field(min_length=1)
    c_id: StrictInt | None = None


class RenameStandClusterRequest(VersionedRequest):
    c_id: StrictInt
    name: str | None = None


class DeleteStandClusterRequest(VersionedRequest):
    c_id: StrictInt


def build_graph_router(
    session: EditorSession,
    save_path: FilePath,
    on_finish: Callable[[], None] | None,
) -> APIRouter:
    router = APIRouter()

    @router.post("/api/draw-connection")
    def draw_connection(item: DrawConnectionRequest) -> GraphCommandResponse:
        try:
            result = session.draw_connection(
                item.start,
                item.end,
                item.intermediate_points,
                aeroway=item.aeroway,
                ref=item.ref,
                expected_revision=item.expected_revision,
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return GraphCommandResponse(
            message="已添加人工连接，可撤销；点击保存持久化",
            revision=result.revision,
        )

    @router.post("/api/restore-options")
    def restore_options(item: RestoreRequest) -> RestoreOptionsResponse:
        if item.start == item.end:
            raise HTTPException(400, "起点和终点不能相同")
        result = session.connection_candidates(
            item.start, item.end, expected_revision=item.expected_revision
        )
        return RestoreOptionsResponse.model_validate(
            {
                "revision": result.revision,
                "current_endpoints": [item.start, item.end],
                "candidates": [
                    {
                        **{
                            name: to_json_value(value)
                            for name, value in candidate.items()
                            if name != "geometry"
                        },
                        "geometry": mapping(candidate["geometry"]),
                    }
                    for candidate in result.value
                ],
            }
        )

    @router.post("/api/restore-confirm")
    def restore_confirm(item: RestoreRequest) -> GraphCommandResponse:
        if item.candidate_id is None:
            raise HTTPException(400, "必须选择一个来源路径")
        try:
            result = session.restore_source_connection(
                item.start,
                item.end,
                item.candidate_id,
                expected_revision=item.expected_revision,
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return GraphCommandResponse(
            message=f"已从原始来源路径恢复派生边，key={result.value!r}",
            revision=result.revision,
        )

    @router.get("/api/merge-candidates")
    def merge_candidates() -> MergeCandidatesResponse:
        with session.lock:
            candidates = session.merge_candidates()
            return MergeCandidatesResponse.model_validate(
                {
                    "revision": session.revision,
                    "candidates": to_json_value(candidates),
                }
            )

    @router.post("/api/merge-nodes-preview")
    def merge_nodes_preview(item: MergeNodesRequest) -> MergeNodesPreviewResponse:
        try:
            result = session.merge_nodes_preview(
                item.node_ids,
                item.canonical_node_id,
                expected_revision=item.expected_revision,
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        value = to_json_value(result.value)
        value["revision"] = result.revision
        return MergeNodesPreviewResponse.model_validate(value)

    @router.post("/api/merge-nodes-confirm")
    def merge_nodes_confirm(item: MergeNodesRequest) -> GraphCommandResponse:
        try:
            result = session.merge_nodes(
                item.node_ids,
                item.canonical_node_id,
                expected_revision=item.expected_revision,
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return GraphCommandResponse(
            message=f"已合并节点，规范节点为 {result.value!r}",
            revision=result.revision,
        )

    @router.post("/api/delete-edge-preview")
    def delete_edge_preview(item: EdgeRequest) -> DeleteEdgePreviewResponse:
        result = session.derived_edge_removal_preview(
            *item.edge.as_tuple(), expected_revision=item.expected_revision
        )
        return DeleteEdgePreviewResponse.model_validate(
            {**result.value, "revision": result.revision}
        )

    @router.post("/api/delete-edge-confirm")
    def delete_edge_confirm(item: EdgeRequest) -> GraphCommandResponse:
        edge = item.edge.as_tuple()
        result = session.remove_derived_edge(*edge, expected_revision=item.expected_revision)
        return GraphCommandResponse(
            message=f"已删除派生边 {edge!r}，SourceEdge 保持不变",
            revision=result.revision,
        )

    @router.post("/api/delete-node-preview")
    def delete_node_preview(item: NodeDeletionRequest) -> DeleteNodePreviewResponse:
        try:
            result = session.node_deletion_plan(item.node, expected_revision=item.expected_revision)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return DeleteNodePreviewResponse.model_validate(
            {**result.value, "revision": result.revision}
        )

    @router.post("/api/delete-node-confirm")
    def delete_node_confirm(item: NodeDeletionRequest) -> GraphCommandResponse:
        try:
            result = session.remove_node_with_pairs(
                item.node,
                item.pair_ids,
                item.discard_unpaired,
                expected_revision=item.expected_revision,
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return GraphCommandResponse(
            message=f"已按所选来源策略删除节点 {item.node!r}",
            revision=result.revision,
        )

    @router.post("/api/split-source-preview")
    def split_source_preview(item: SourceSplitRequest) -> SplitSourcePreviewResponse:
        try:
            result = session.source_split_preview(
                *item.edge.as_tuple(),
                item.longitude,
                item.latitude,
                expected_revision=item.expected_revision,
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        value = to_json_value(result.value)
        value["revision"] = result.revision
        for candidate in value["candidates"]:
            candidate["id"] = candidate.pop("canonical_node_id")
        return SplitSourcePreviewResponse.model_validate(value)

    @router.post("/api/split-source-confirm")
    def split_source_confirm(item: SourceSplitRequest) -> GraphCommandResponse:
        try:
            node = session.split_source_edge(
                *item.edge.as_tuple(),
                item.longitude,
                item.latitude,
                item.osm_node_id,
                expected_revision=item.expected_revision,
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return GraphCommandResponse(
            message=f"已在 SourceEdge 上使用节点 {node.value!r} 切分",
            revision=node.revision,
        )

    @router.post("/api/manual-snap-preview")
    def manual_snap_preview(item: ManualSnapRequest) -> ManualSnapPreviewResponse:
        edge = item.edge.as_tuple()
        try:
            result = session.manual_snap_preview(
                item.node, *edge, expected_revision=item.expected_revision
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return ManualSnapPreviewResponse.model_validate(
            {**to_json_value(result.value), "revision": result.revision}
        )

    @router.post("/api/manual-snap-confirm")
    def manual_snap_confirm(item: ManualSnapRequest) -> GraphCommandResponse:
        edge = item.edge.as_tuple()
        try:
            result = session.manual_snap_node_to_edge(
                item.node, *edge, expected_revision=item.expected_revision
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return GraphCommandResponse(
            message=f"已将节点 {item.node!r} 人工接入目标边",
            revision=result.revision,
        )

    @router.post("/api/update-node")
    def update_node(item: UpdatedNodeAttributes) -> GraphCommandResponse:
        result = session.update_node_attributes(
            item.node, item.attributes, expected_revision=item.expected_revision
        )
        return GraphCommandResponse(
            message=f"已更新节点 {item.node!r} 的属性",
            revision=result.revision,
        )

    @router.post("/api/update-edge")
    def update_edge(item: UpdatedEdgeAttributes) -> GraphCommandResponse:
        edge = item.edge.as_tuple()
        result = session.update_edge_attributes(
            *edge, item.attributes, expected_revision=item.expected_revision
        )
        return GraphCommandResponse(message=f"已更新边 {edge!r} 的属性", revision=result.revision)

    @router.post("/api/stand-clusters/create")
    def create_stand_cluster(item: CreateStandClusterRequest) -> GraphCommandResponse:
        try:
            result = session.create_stand_cluster(
                [edge.as_tuple() for edge in item.edges],
                name=item.name,
                expected_revision=item.expected_revision,
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        cluster = result.value
        label = f" #{cluster.c_id}（{cluster.name}）" if cluster.name else f" #{cluster.c_id}"
        return GraphCommandResponse(
            message=f"已新建机位类别{label}，包含 {len(cluster.stands)} 条机位边",
            revision=result.revision,
        )

    @router.post("/api/stand-clusters/assign")
    def assign_stand_cluster(item: AssignStandClusterRequest) -> GraphCommandResponse:
        try:
            result = session.assign_stands_to_cluster(
                [edge.as_tuple() for edge in item.edges],
                item.c_id,
                expected_revision=item.expected_revision,
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        if item.c_id is None:
            message = f"已将 {len(item.edges)} 条机位边移出类别"
        else:
            message = f"已将 {len(item.edges)} 条机位边归入类别 #{item.c_id}"
        return GraphCommandResponse(message=message, revision=result.revision)

    @router.post("/api/stand-clusters/rename")
    def rename_stand_cluster(item: RenameStandClusterRequest) -> GraphCommandResponse:
        try:
            result = session.rename_stand_cluster(
                item.c_id,
                item.name,
                expected_revision=item.expected_revision,
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        label = result.value.name or f"Cluster #{item.c_id}"
        return GraphCommandResponse(
            message=f"已更新类别 #{item.c_id} 名称为 {label}",
            revision=result.revision,
        )

    @router.post("/api/stand-clusters/delete")
    def delete_stand_cluster(item: DeleteStandClusterRequest) -> GraphCommandResponse:
        result = session.delete_stand_cluster(
            item.c_id,
            expected_revision=item.expected_revision,
        )
        return GraphCommandResponse(
            message=f"已删除机位类别 #{item.c_id}",
            revision=result.revision,
        )

    @router.post("/api/save")
    def save(item: VersionedRequest) -> GraphCommandResponse:
        result = session.save(save_path, expected_revision=item.expected_revision)
        output = result.value
        return GraphCommandResponse(
            message=(
                f"已保存 {output} · {session.graph.number_of_nodes()} 节点 · "
                f"{session.graph.number_of_edges()} 边"
            ),
            revision=result.revision,
        )

    @router.post("/api/undo")
    def undo(item: VersionedRequest) -> GraphCommandResponse:
        try:
            result = session.undo(expected_revision=item.expected_revision)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return GraphCommandResponse(message="已撤销上一步操作", revision=result.revision)

    @router.post("/api/finish")
    def finish(item: VersionedRequest) -> GraphCommandResponse:
        if on_finish is None:
            raise HTTPException(400, "当前为独立编辑模式")
        result = session.finish(save_path, on_finish, expected_revision=item.expected_revision)
        output = result.value
        return GraphCommandResponse(
            message=f"已保存 {output}，编辑完成，正在返回 AirportGraph",
            revision=result.revision,
        )

    return router
