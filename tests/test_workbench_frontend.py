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
const lines=source.split(/\r?\n/);
for(const name of ["identityKey","nodeKey","sortedNodeReviewSnapshot"]){
  vm.runInThisContext(lines.find(line=>line.startsWith(`function ${name}`)));
}
const features=[
  {properties:{node_id:"'b'",id:{type:"str",value:"b"}}},
  {properties:{node_id:"2",id:{type:"int",value:"2"}}},
  {properties:{node_id:"1",id:{type:"int",value:"1"}}},
  {properties:{node_id:"'a'",id:{type:"str",value:"a"}}}
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
const lines=source.split(/\r?\n/);
vm.runInThisContext(lines.find(line=>line.startsWith("function identityKey")));
vm.runInThisContext(lines.find(line=>line.startsWith("function nodeKey")));
const integer={properties:{node_id:"1",id:{type:"int",value:"1"}}};
const string={properties:{node_id:"'1'",id:{type:"str",value:"1"}}};
const refreshedInteger={properties:{
  node_id:"1",id:{type:"int",value:"1"},parking_position_node:true
}};
const refreshedString={properties:{
  node_id:"'1'",id:{type:"str",value:"1"},runway_access_node:true
}};
const index=new Map([refreshedInteger,refreshedString].map(feature=>[nodeKey(feature),feature]));
const snapshot=[integer,string].map(feature=>index.get(nodeKey(feature)));
if(snapshot[0]!==refreshedInteger||snapshot[1]!==refreshedString){
  throw new Error("typed identities collided during refresh");
}
if(new Set(snapshot).size!==2)throw new Error("review snapshot repeated a mixed-type node");
"""

    subprocess.run([node, "-e", script, str(source_path)], check=True)


def test_revision_conflict_invalidates_operation_refreshes_without_retry() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for frontend behavior tests")
    source_path = Path("src/airport_workbench/static/app.js").resolve()
    script = r"""
const fs=require("fs"),vm=require("vm");
const source=fs.readFileSync(process.argv[1],"utf8");
const start=source.indexOf("async function readResponse");
const end=source.indexOf("function clearPreview");
let fetchCalls=0,closed=0,refreshed=0;
const context={
  JSON,Error,
  busy:{classList:{remove(){},add(){}}},
  fetch:async()=>{fetchCalls++;return{
    ok:false,status:409,
    text:async()=>JSON.stringify({detail:{
      code:"revision_conflict",message:"图已变更，请重新检查操作",current_revision:2
    }})
  }},
  closeDetails:()=>{closed++;},loadState:async()=>{refreshed++;},
  firstNode:{},firstNodeRevision:0,mergeNodeIds:[{}],mergeSelectionRevision:0,
  conflictNotice:false,status:{textContent:""}
};
vm.createContext(context);vm.runInContext(source.slice(start,end),context);
(async()=>{
  try{await context.post("/api/test",{expected_revision:1});throw new Error("accepted");}
  catch(error){if(error.code!=="revision_conflict")throw error;}
  if(fetchCalls!==1)throw new Error("conflicting mutation was retried");
  if(closed!==1||refreshed!==1)throw new Error("old operation was not invalidated and refreshed");
  if(context.status.textContent!=="图已变更，请重新检查操作"){
    throw new Error("wrong conflict message");
  }
  if(context.firstNode!==null||context.mergeNodeIds.length){
    throw new Error("old selection survived");
  }
})().catch(error=>{console.error(error);process.exit(1);});
"""

    subprocess.run([node, "-e", script, str(source_path)], check=True)


def test_observation_location_waits_for_visible_map_and_uses_finite_zoom() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for frontend behavior tests")
    source_path = Path("src/airport_workbench/static/flights-v2.js").resolve()
    script = r"""
const fs=require("fs"),vm=require("vm");
const source=fs.readFileSync(process.argv[1],"utf8"),lines=source.split(/\r?\n/);
let zoom=null,invalidated=0,switched=false;
const context={
  Number,observationHighlight:null,
  map:{
    removeLayer(){},invalidateSize(){invalidated++;},getZoom(){return Infinity;},
    setView(_point,value){zoom=value;}
  },
  L:{circleMarker(){return{addTo(){return {};}}}},
  document:{querySelector(){return{disabled:true};}},
  switchMainTab(tab){switched=tab==="map";},
  requestAnimationFrame(callback){callback();}
};
vm.createContext(context);
for(const name of ["observationCoordinate","locateObservation"]){
  vm.runInContext(lines.find(line=>line.startsWith(`function ${name}`)),context);
}
context.locateObservation({longitude:116.5,latitude:40.1});
if(!switched||invalidated!==1||zoom!==18){
  throw new Error(`bad map transition ${switched}/${invalidated}/${zoom}`);
}
"""
    subprocess.run([node, "-e", script, str(source_path)], check=True)


def test_observation_detail_only_latest_request_can_render() -> None:
    source = Path("src/airport_workbench/static/flights-v2.js").read_text(encoding="utf-8")
    detail = source[source.index("async function showDetail") :]
    detail = detail[: detail.index("async function selectFiltered")]

    assert "const requestId=++detailRequest" in detail
    assert "if(requestId!==detailRequest)return" in detail
    assert "if(requestId===detailRequest)showFlightError" in detail
    assert detail.index("if(requestId!==detailRequest)return") < detail.index(
        "currentDetailKey=key"
    )


def test_delayed_observation_page_does_not_reopen_observations_tab() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for frontend behavior tests")
    source_path = Path("src/airport_workbench/static/flights-v2.js").resolve()
    script = r"""
const fs=require("fs"),vm=require("vm");
const source=fs.readFileSync(process.argv[1],"utf8");
const start=source.indexOf("async function showDetail");
const end=source.indexOf("async function selectFiltered",start);
let release,currentTab="map";
const pending=new Promise(resolve=>{release=resolve;});
const button={},content={scrollTop:0,innerHTML:"",
  querySelector(){return button;},querySelectorAll(){return[];}};
const simple={textContent:""};
const context={
  detailRequest:0,detailState:new Map(),currentDetailKey:null,
  fetch(){return pending;},readResponse:async value=>value,
  encodeURIComponent,STATUS_LABELS:{unmatched:"未匹配"},
  escapeHtml:value=>String(value),observationCoordinate:()=>null,
  showFlightError(message){throw new Error(message);},
  switchMainTab(tab){currentTab=tab;},
  document:{querySelector(selector){
    if(selector==="#observations-content")return content;
    return simple;
  }}
};
vm.createContext(context);
vm.runInContext(source.slice(start,end),context);
(async()=>{
  const request=context.showDetail("flight-a",2,false);
  if(currentTab!=="observations")throw new Error("detail did not open immediately");
  context.switchMainTab("map");
  release({
    summary:{flight_number:"A",flight_id:"a",movement_type:"arrival",
      point_count:0,start_time:"",end_time:""},
    match:{status:"unmatched"},observation_columns:[],observations:[],
    inconsistent_fields:{},observation_page:2,observation_pages:2,
    observation_total:0
  });
  await request;
  if(currentTab!=="map")throw new Error("delayed response reopened observations");
})().catch(error=>{console.error(error);process.exit(1);});
"""
    subprocess.run([node, "-e", script, str(source_path)], check=True)


def test_flight_location_messages_distinguish_geometry_states() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for frontend behavior tests")
    source_path = Path("src/airport_workbench/static/flights-v2.js").resolve()
    script = r"""
const fs=require("fs"),vm=require("vm");
const source=fs.readFileSync(process.argv[1],"utf8"),lines=source.split(/\r?\n/);
const messages=[],mapSelection=new Map(),geometries=new Map();
const context={
  mapSelection,geometries,messages,
  setStatus(message){messages.push(message);},applyFocus(){},
  map:{fitBounds(){throw new Error("unexpected fit");}},
  L:{latLngBounds(){return{extend(){},isValid(){return false;}}}}
};
vm.createContext(context);
for(const name of ["boundsFor","focusFlight"]){
  vm.runInContext(lines.find(line=>line.startsWith(`function ${name}`)),context);
}
mapSelection.set("loading",{state:"loading"});
mapSelection.set("error",{state:"error"});
mapSelection.set("empty",{state:"empty"});
context.focusFlight("loading");context.focusFlight("error");context.focusFlight("empty");
const expected=["该航班轨迹正在加载","该航班轨迹加载失败，可点击重试","该航班没有有效坐标"];
if(JSON.stringify(messages)!==JSON.stringify(expected))throw new Error(JSON.stringify(messages));
"""
    subprocess.run([node, "-e", script, str(source_path)], check=True)


def test_narrow_details_switches_to_and_back_from_topology_panel() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for frontend behavior tests")
    source_path = Path("src/airport_workbench/static/app.js").resolve()
    source_text = source_path.read_text(encoding="utf-8")
    observer_wiring = (
        'new ResizeObserver(refreshMapLayout).observe(document.querySelector(".workspace"))'
    )
    assert observer_wiring in source_text
    script = r"""
const fs=require("fs"),vm=require("vm");
const source=fs.readFileSync(process.argv[1],"utf8"),lines=source.split(/\r?\n/);
const classes=initial=>({
  values:new Set(initial),contains(v){return this.values.has(v);},
  add(v){this.values.add(v);},remove(v){this.values.delete(v);},
  toggle(v,force){force?this.add(v):this.remove(v);}
});
const topologyPanel={classList:classes([])};
const details={classList:classes(["hidden"])};
const topologyBack={classList:classes(["hidden"])};
const toggle={classList:classes([])};
let invalidations=0;
const context={
  topologyPanel,details,topologyBack,narrowDetailsReturnToTopology:false,
  topologyInspectionActive:false,topologyPreviousNodeVisibility:false,
  currentState:{flight_mode:true},nodeLayer:null,edgeGroup:null,renderEdges(){},
  window:{matchMedia(){return{matches:true};}},requestAnimationFrame(callback){callback();},
  map:{invalidateSize(){invalidations++;}},
  document:{querySelector(selector){if(selector==="#topology-toggle")return toggle;}}
};
vm.createContext(context);
const names=["refreshMapLayout","isNarrowLayout","shouldSwapTopologyPanel",
  "setTopologyInspection","openDetails","returnToTopology"];
for(const name of names){
  vm.runInContext(lines.find(line=>line.startsWith(`function ${name}`)),context);
}
context.openDetails();
if(topologyPanel.classList.contains("hidden")===false||
   details.classList.contains("hidden")||
   topologyBack.classList.contains("hidden")){
  throw new Error("details did not replace topology");
}
context.returnToTopology();
if(topologyPanel.classList.contains("hidden")||
   !details.classList.contains("hidden")){
  throw new Error("return did not restore topology");
}
if(invalidations!==2)throw new Error(`expected two map resizes, got ${invalidations}`);
"""
    subprocess.run([node, "-e", script, str(source_path)], check=True)


def test_initial_view_and_flight_topology_styles_are_wired() -> None:
    source = Path("src/airport_workbench/static/app.js").read_text(encoding="utf-8")

    initial_fit = (
        "if(!fitted){const nodeBounds=nodeLayer.getBounds(),"
        "edgeBounds=edgeLayer.getBounds()"
    )
    assert initial_fit in source
    assert "if(!data.flight_mode&&!fitted" not in source
    assert 'color:splitValidation?feature.properties.validation_color' in source
    assert "flightMode&&!topologyInspectionActive?3:2.8" in source
    assert "Math.max(Number(p.radius)||0,4)" in source
    swap_rule = (
        "function shouldSwapTopologyPanel(){return "
        "Boolean(currentState?.flight_mode)||isNarrowLayout();}"
    )
    assert swap_rule in source
    assert "setTopologyInspection(opening)" in source
