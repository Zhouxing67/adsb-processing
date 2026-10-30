import shutil
import subprocess
from pathlib import Path

import pytest


def test_match_poll_compares_with_rendered_geometry_version() -> None:
    source = Path("src/airport_workbench/static/flights-v2.js").read_text(encoding="utf-8")

    assert (
        "function needsGeometryRefresh(key,result){return "
        "geometries.get(key)?.resultSignature!==geometrySignature(result);}" in source
    )
    poll = source[source.index("async function pollMatches()") :]
    poll = poll[: poll.index("function restoreSelections")]
    assert "needsGeometryRefresh(result.flight_key,result)" in poll
    assert "geometrySignature(previous" not in poll


def test_catalogue_search_only_applies_on_enter_and_uses_committed_term() -> None:
    source = Path("src/airport_workbench/static/flights-v2.js").read_text(encoding="utf-8")

    assert 'document.querySelector("#flight-search").oninput' not in source
    assert 'document.querySelector("#flight-search").onkeydown' in source
    assert 'event.key!=="Enter"||event.isComposing||event.keyCode===229' in source
    assert 'activeSearch=event.currentTarget.value.trim()' in source
    assert 'if(activeSearch)params.set("q",activeSearch)' in source
    assert 'q:activeSearch' in source


def test_catalogue_page_jump_and_point_filter_validate_before_query() -> None:
    source = Path("src/airport_workbench/static/flights-v2.js").read_text(encoding="utf-8")

    jump = source[source.index("function jumpToPage()") :]
    jump = jump[: jump.index("async function showDetail")]
    assert "page<1||page>cataloguePages" in jump
    assert "queryCatalogue(page)" in jump
    assert jump.index("page<1||page>cataloguePages") < jump.index("queryCatalogue(page)")
    assert "minimum>maximum" in source
    assert "maximum>datasetMaxPoints" in source
    assert "queryCatalogue(1)" in source
    assert "dataset_max_points" in source
    assert "total_pages" in source


def test_catalogue_coordinator_defers_background_refresh_and_preserves_draft() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for frontend behavior tests")
    source_path = Path("src/airport_workbench/static/flights-v2.js").resolve()
    script = r"""
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync(process.argv[1], "utf8");
vm.runInThisContext(source.slice(0, source.indexOf("const SLOT_COLORS")));
(async () => {
  const coordinator = new CatalogueQueryCoordinator();
  let finishUser;
  const userRequest = new Promise(resolve => { finishUser = resolve; });
  let backgroundRequests = 0;
  let refreshes = 0;
  coordinator.run({background:false, request:() => userRequest, refresh:() => {
    refreshes += 1;
    coordinator.run({
      background:true,
      request:() => { backgroundRequests += 1; },
      refresh:() => {}
    });
  }});
  coordinator.run({
    background:true,
    request:() => { backgroundRequests += 1; },
    refresh:() => {}
  });
  if (backgroundRequests !== 0) throw new Error("background refresh ran during user query");
  finishUser();
  await new Promise(resolve => setImmediate(resolve));
  if (refreshes !== 1 || backgroundRequests !== 1) {
    throw new Error(`expected one deferred refresh, got ${refreshes}/${backgroundRequests}`);
  }
  const draft = new PointFilterDraft();
  draft.edit();
  if (draft.shouldSync()) throw new Error("edited draft would be overwritten");
  draft.commit();
  if (!draft.shouldSync()) throw new Error("committed draft did not resync");
  const nodes = [
    {inert:false, attributes:{}, setAttribute(name, value){this.attributes[name]=value;}},
    {inert:false, attributes:{}, setAttribute(name, value){this.attributes[name]=value;}}
  ];
  setCatalogueControlsInitializing(nodes, true);
  if (nodes.some(node => !node.inert || node.attributes["aria-busy"] !== "true")) {
    throw new Error("catalogue controls were not locked during initialization");
  }
  setCatalogueControlsInitializing(nodes, false);
  if (nodes.some(node => node.inert || node.attributes["aria-busy"] !== "false")) {
    throw new Error("catalogue controls were not unlocked after initialization");
  }
  const initializeStart = source.indexOf("async function initializeCatalogue()");
  const initializeEnd = source.indexOf("initializeCatalogue();", initializeStart);
  const context = {
    catalogueControlRegions: [],
    lockEvents: [],
    queryCalls: 0,
    restoredFilters: {minPoints:10, maxPoints:20, page:3},
    appliedMinPoints: 0,
    appliedMaxPoints: null,
    datasetMaxPoints: 0,
    restoredSelections: 0
  };
  context.setCatalogueControlsInitializing = (_nodes, value) => context.lockEvents.push(value);
  context.queryCatalogue = async () => { context.queryCalls += 1; return false; };
  context.restoreSelections = () => { context.restoredSelections += 1; };
  vm.createContext(context);
  vm.runInContext(
    source.slice(initializeStart, initializeEnd) + ";globalThis.runInitialize=initializeCatalogue;",
    context
  );
  await context.runInitialize();
  if (context.queryCalls !== 1 || context.appliedMaxPoints !== null) {
    throw new Error("failed first load restored stale point limits");
  }
  if (context.lockEvents.join(",") !== "true,false" || context.restoredSelections !== 1) {
    throw new Error("failed initialization did not clean up controls and selections");
  }
})().catch(error => { console.error(error); process.exit(1); });
"""

    subprocess.run([node, "-e", script, str(source_path)], check=True)


def test_catalogue_initialization_locks_controls_until_restore_finishes() -> None:
    source = Path("src/airport_workbench/static/flights-v2.js").read_text(encoding="utf-8")
    initialize = source[source.index("async function initializeCatalogue()") :]
    initialize = initialize[: initialize.index("initializeCatalogue();")]

    lock = "setCatalogueControlsInitializing(catalogueControlRegions,true)"
    unlock = "setCatalogueControlsInitializing(catalogueControlRegions,false)"
    assert lock in initialize
    assert "finally{" in initialize
    assert unlock in initialize
    assert initialize.index(lock) < initialize.index("await queryCatalogue(1)")
    assert "const initialized=await queryCatalogue(1);if(!initialized)return" in initialize
    assert initialize.index("finally{") < initialize.index(unlock)


def test_business_node_markers_and_point_review_are_wired() -> None:
    source = Path("src/airport_workbench/static/app.js").read_text(encoding="utf-8")
    html = Path("src/airport_workbench/static/index.html").read_text(encoding="utf-8")

    assert 'p.parking_position_node?"P":""' in source
    assert 'p.runway_access_node?"R":""' in source
    assert "business-annotations" in source
    assert "/business-annotations" in source
    assert "sortedNodeReviewSnapshot(nodeFeatures)" in source
    assert "nodeFeatureIndex.set(nodeKey(feature),feature)" in source
    assert "nodeFeatureIndex.get(nodeKey(feature))" in source
    assert "if(selected)selectNode(selected);else closeDetails()" in source
    assert "if(current)showNodeProperties(current);else closeDetails()" in source
    assert "lastTopologyRevision!==data.topology_revision" in source
    assert "遍历位置" in source
    assert "已到最后一个节点；这不表示全部复核通过" in source
    assert 'id="node-review-start"' in html
    assert 'id="node-review-prev"' in html
    assert 'id="node-review-next"' in html
    assert 'id="node-review-end"' in html


def test_point_review_snapshot_sort_executes_for_mixed_node_types() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for frontend behavior tests")
    source_path = Path("src/airport_workbench/static/app.js").resolve()
    script = r"""
const fs=require("fs"),vm=require("vm");
const source=fs.readFileSync(process.argv[1],"utf8");
const definition=source.split(/\r?\n/).find(
  line=>line.startsWith("function sortedNodeReviewSnapshot")
);
vm.runInThisContext(definition);
const features=[
  {properties:{node_id:"'b'",node_sort_key:["str","'b'"]}},
  {properties:{node_id:"2",node_sort_key:["int","2"]}},
  {properties:{node_id:"1",node_sort_key:["int","1"]}},
  {properties:{node_id:"'a'",node_sort_key:["str","'a'"]}}
];
const ordered=sortedNodeReviewSnapshot(features).map(item=>item.properties.node_id);
if(JSON.stringify(ordered)!==JSON.stringify(["1","2","'a'","'b'"])){
  throw new Error(`unexpected review order: ${JSON.stringify(ordered)}`);
}
if(new Set(ordered).size!==features.length)throw new Error("snapshot lost or repeated nodes");
"""

    subprocess.run([node, "-e", script, str(source_path)], check=True)


def test_point_review_refresh_preserves_mixed_node_identities() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for frontend behavior tests")
    source_path = Path("src/airport_workbench/static/app.js").resolve()
    script = r"""
const fs=require("fs"),vm=require("vm");
const source=fs.readFileSync(process.argv[1],"utf8");
const definition=source.split(/\r?\n/).find(line=>line.startsWith("function nodeKey"));
vm.runInThisContext(definition);
const integer={properties:{node_id:"1",node_sort_key:["int","1"]}};
const string={properties:{node_id:"'1'",node_sort_key:["str","'1'"]}};
const refreshedInteger={properties:{
  node_id:"1",node_sort_key:["int","1"],parking_position_node:true
}};
const refreshedString={properties:{
  node_id:"'1'",node_sort_key:["str","'1'"],runway_access_node:true
}};
const index=new Map([refreshedInteger,refreshedString].map(feature=>[nodeKey(feature),feature]));
const snapshot=[integer,string].map(feature=>index.get(nodeKey(feature)));
if(snapshot[0]!==refreshedInteger||snapshot[1]!==refreshedString){
  throw new Error("typed identities collided during refresh");
}
if(new Set(snapshot).size!==2)throw new Error("review snapshot repeated a mixed-type node");
"""

    subprocess.run([node, "-e", script, str(source_path)], check=True)
