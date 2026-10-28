const map = L.map("map", {preferCanvas: false, zoomControl: false, maxZoom: 26});
map.createPane("edgeCasingPane"); map.getPane("edgeCasingPane").style.zIndex = 410;
map.createPane("edgesPane"); map.getPane("edgesPane").style.zIndex = 420;
map.createPane("flightPane"); map.getPane("flightPane").style.zIndex = 510;
map.createPane("pathPane"); map.getPane("pathPane").style.zIndex = 530;
map.createPane("selectionEdgePane"); map.getPane("selectionEdgePane").style.zIndex = 610;
map.createPane("nodesPane"); map.getPane("nodesPane").style.zIndex = 650;
map.createPane("previewPane"); map.getPane("previewPane").style.zIndex = 660;
map.createPane("selectionPane"); map.getPane("selectionPane").style.zIndex = 670;

const osm = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {attribution: "© OpenStreetMap contributors",maxNativeZoom:19,maxZoom:26}).addTo(map);
const satellite = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {attribution: "Esri, Maxar, Earthstar Geographics",maxNativeZoom:19,maxZoom:26});
const blankBase = L.layerGroup();
const layers = L.control.layers({"OpenStreetMap": osm, "ESRI 卫星": satellite, "无底图（精细编辑）": blankBase}, {}, {collapsed: false, position: "topleft"}).addTo(map);
document.querySelector("#layer-control-slot").appendChild(layers.getContainer());

let mode = "inspect", nodeLayer, edgeLayer, edgeGroup, previewLayer, endpointLayer, selectionLayer;
let splitValidation = false, currentState = null;
let dataLayers = [];
let nodeFeatures = [], fitted = false, savePath = "", firstNode = null;
let mergeNodeTokens = [];
const nodeFeatureIndex = new Map(), edgeSearchIndex = new Map(), edgeTokenIndex = new Map();
const status = document.querySelector("#status"), busy = document.querySelector("#busy");
const details = document.querySelector("#details"), detailsContent = document.querySelector("#details-content");
const messages = {
  inspect: "查看模式 · 点击节点或派生边查看来源信息",
  split: "补充分割点 · 点击派生边上的正确位置；优先复用附近的原始 OSM Node",
  restore: "恢复来源连接 · 依次点击两个图节点，从原始 SourceEdge 网络恢复曲线",
  merge: "合并节点 · 从候选列表选择，或连续点击节点后停止选择",
  snap: "人工吸附到边 · 先选误差节点，再选它本应接入的派生边",
  delete: "删除 / 简化 · 删除边只改拓扑；删除节点可人工选择半边重组"
};

function setStatus(message) { status.textContent = message; }
function escapeHtml(value) { return String(value ?? "—").replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"})[c]); }
function normalizeId(value) { return String(value ?? "").trim().replace(/^['"]|['"]$/g, ""); }
function edgePairKey(u, v) { return [normalizeId(u), normalizeId(v)].sort().join("|"); }
async function readResponse(response) { const text = await response.text(); let value; try { value = text ? JSON.parse(text) : {}; } catch { value = {detail:text}; } if (!response.ok) throw new Error(value.detail || value.message || `HTTP ${response.status}`); return value; }
async function post(path, body, reload = false) {
  busy.classList.remove("hidden");
  try { const value = await readResponse(await fetch(path, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)})); if (reload) await loadState(); return value; }
  finally { busy.classList.add("hidden"); }
}
function clearPreview() { if (previewLayer) { map.removeLayer(previewLayer); previewLayer = null; } }
function clearEndpointHighlight() { if (endpointLayer) { map.removeLayer(endpointLayer); endpointLayer = null; } }
function clearSelection() { if (selectionLayer) { map.removeLayer(selectionLayer); selectionLayer = null; } }
function closeDetails() { details.classList.add("hidden"); clearPreview(); clearEndpointHighlight(); clearSelection(); }
function showProperties(title, properties) {
  const ignored = new Set(["token", "validation_color", "editable_attributes"]);
  const rows = Object.entries(properties).filter(([key]) => !ignored.has(key)).map(([key,value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value)}</dd>`).join("");
  detailsContent.innerHTML = `<h2>${escapeHtml(title)}</h2><dl>${rows}</dl>`; details.classList.remove("hidden");
}
function showConfirmation(title, html, confirmText, onConfirm) {
  detailsContent.innerHTML = `<h2>${escapeHtml(title)}</h2>${html}<div class="attribute-actions"><button id="cancel-action" class="secondary-button">取消</button><button id="confirm-action" class="primary-button">${escapeHtml(confirmText)}</button></div>`;
  details.classList.remove("hidden");
  document.querySelector("#cancel-action").onclick = closeDetails;
  document.querySelector("#confirm-action").onclick = onConfirm;
}
function showGeometry(geometry, color = "#db2777") { clearPreview(); previewLayer = L.geoJSON({type:"Feature", geometry}, {pane:"previewPane", interactive:false, style:{color,weight:9,opacity:.92,lineCap:"round",lineJoin:"round"}}).addTo(map); }
function highlightEdgeEndpoints(feature) {
  clearEndpointHighlight();
  const markers=[feature.properties.u,feature.properties.v].map(identifier=>nodeFeatureIndex.get(normalizeId(identifier))).filter(Boolean).map(node=>{
    const [longitude,latitude]=node.geometry.coordinates;
    return L.circleMarker([latitude,longitude],{pane:"selectionPane",radius:11,color:"#facc15",weight:4,fill:false,interactive:false});
  });
  endpointLayer=L.layerGroup(markers).addTo(map);
}
function selectEdge(feature, fit = false) {
  clearSelection(); highlightEdgeEndpoints(feature);
  selectionLayer=L.geoJSON({type:"Feature",geometry:feature.geometry},{pane:"selectionEdgePane",interactive:false,style:{color:"#7e22ce",weight:10,opacity:.9}}).addTo(map);
  if(fit) map.fitBounds(selectionLayer.getBounds(),{padding:[80,80],maxZoom:24});
  showProperties(`派生边 ${feature.properties.edge_id}`,feature.properties);
}
function selectNode(feature, fit = false) {
  clearSelection(); clearEndpointHighlight();
  const id=normalizeId(feature.properties.node_id);
  const incident=currentState.edges.features.filter(edge=>normalizeId(edge.properties.u)===id||normalizeId(edge.properties.v)===id);
  const neighbours=new Set(incident.map(edge=>normalizeId(edge.properties.u)===id?normalizeId(edge.properties.v):normalizeId(edge.properties.u)));
  const layersToShow=[];
  const seenGeometry=new Set();
  incident.forEach(edge=>{const geometryKey=JSON.stringify(edge.geometry);if(seenGeometry.has(geometryKey))return;seenGeometry.add(geometryKey);layersToShow.push(L.geoJSON({type:"Feature",geometry:edge.geometry},{pane:"selectionEdgePane",interactive:false,style:{color:"#2563eb",weight:6,opacity:.82,lineCap:"round",lineJoin:"round"}}));});
  neighbours.forEach(neighbour=>{const item=nodeFeatureIndex.get(neighbour);if(item){const [x,y]=item.geometry.coordinates;layersToShow.push(L.circleMarker([y,x],{pane:"selectionPane",radius:7,color:"#fff",fillColor:"#0891b2",fillOpacity:1,weight:3,interactive:false}));}});
  const [x,y]=feature.geometry.coordinates;
  layersToShow.push(L.circleMarker([y,x],{pane:"selectionPane",radius:14,color:"#2563eb",fill:false,opacity:.45,weight:2,interactive:false}));
  layersToShow.push(L.circleMarker([y,x],{pane:"selectionPane",radius:9,color:"#fff",fillColor:"#2563eb",fillOpacity:1,weight:3,interactive:false}));
  selectionLayer=L.layerGroup(layersToShow).addTo(map);
  if(fit) map.setView([y,x],Math.max(map.getZoom(),22));
  showProperties(`节点 ${feature.properties.node_id}`,feature.properties);
}
function highlightMergeNodes(nodes) {
  clearSelection();
  const markers=nodes.map((node,index)=>{const [x,y]=node.position;return L.circleMarker([y,x],{pane:"selectionPane",radius:index===0?13:11,color:"#7e22ce",fillColor:index===0?"#facc15":"#22d3ee",fillOpacity:1,weight:4,interactive:false});});
  selectionLayer=L.layerGroup(markers).addTo(map);
  if(markers.length) map.fitBounds(L.featureGroup(markers).getBounds(),{padding:[100,100],maxZoom:26});
}

async function previewRestore(start, end) {
  try {
    const result = await post("/api/restore-options", {start, end});
    if (!result.candidates.length) { firstNode = null; return setStatus("原始 OSM 来源网络中没有可靠的短路径候选"); }
    const options = result.candidates.map((candidate,index) => `<label class="source-option"><input type="radio" name="source-choice" value="${index}" ${index===0?"checked":""}><span>${escapeHtml(candidate.source_ids.join(" + "))}<br>OSM way ${escapeHtml(candidate.osm_way_ids.join(" + "))} · ${candidate.length_m.toFixed(2)} m</span></label>`).join("");
    showGeometry(result.candidates[0].geometry);
    showConfirmation("从 OSM 恢复连接", `<p>端点：${escapeHtml(result.current_endpoints.join(" — "))}</p><div class="source-options">${options}</div><p class="field-note">geometry 将从完整 SourceEdge 恢复，不会画直线。</p>`, "恢复连接", async () => {
      const index = Number(document.querySelector('input[name="source-choice"]:checked').value); const candidate = result.candidates[index];
      closeDetails(); try { const response = await post("/api/restore-confirm", {start,end,candidate_id:candidate.candidate_id}, true); setStatus(response.message); } catch(error) { setStatus(`恢复失败：${error.message}`); }
    });
    document.querySelectorAll('input[name="source-choice"]').forEach(input => input.onchange = () => showGeometry(result.candidates[Number(input.value)].geometry));
  } catch(error) { setStatus(`无法恢复：${error.message}`); }
  firstNode = null;
}

async function previewMerge(request) {
  try {
    const result=await post("/api/merge-nodes-preview",request);
    highlightMergeNodes(result.nodes);
    const choices=result.nodes.map((node,index)=>`<label class="source-option"><input type="radio" name="merge-canonical" value="${index}" ${node.node_id===result.canonical_node_id?"checked":""}><span>${escapeHtml(node.node_id)} · ${node.manual?"人工图节点":"OSM 图节点"}，度 ${node.degree}<br>${escapeHtml(node.source_ids.join(" + ")||"无 OSM SourceEdge 归属")}</span></label>`).join("");
    const warnings=result.warnings.map(item=>`<p class="warning">${escapeHtml(item)}</p>`).join("");
    showConfirmation("合并节点预览",`<dl><dt>成员</dt><dd>${escapeHtml(result.node_ids.join(", "))}</dd><dt>最大距离</dt><dd>${result.max_distance_m.toFixed(3)} m</dd><dt>受影响边</dt><dd>${result.affected_edges.length}</dd><dt>原始来源</dt><dd>SourceEdge 不会修改</dd></dl><h3>选择规范节点</h3><div class="source-options">${choices}</div>${warnings}`,"确认合并",async()=>{
      const index=Number(document.querySelector('input[name="merge-canonical"]:checked').value);
      const body={node_ids:result.node_ids,canonical_node_id:result.nodes[index].node_id};
      closeDetails();try{const response=await post("/api/merge-nodes-confirm",body,true);mergeNodeTokens=[];setStatus(response.message);}catch(error){setStatus(`合并失败：${error.message}`);}
    });
  } catch(error){setStatus(`无法合并：${error.message}`);}
}

async function openMergeCandidates() {
  try {
    const result=await readResponse(await fetch("/api/merge-candidates"));
    const rows=result.candidates.map((candidate,index)=>`<div class="merge-candidate"><strong>候选 ${index+1} · 最大距离 ${candidate.max_distance_m.toFixed(3)} m</strong><div class="candidate-nodes">${candidate.nodes.map((node,nodeIndex)=>`<button class="candidate-node secondary-button" data-candidate="${index}" data-node="${nodeIndex}">${escapeHtml(node.node_id)}</button>`).join("")}</div><button class="candidate-use primary-button" data-candidate="${index}">检查并合并</button></div>`).join("");
    detailsContent.innerHTML=`<h2>疑似重复图节点</h2><p class="field-note">只检查现有图节点（包括人工节点），不搜索尚未成为图节点的内部 OSM Node。列表只提供候选，不会自动合并。</p><div class="source-options">${rows||"<p>没有 0.5 米内的候选组</p>"}</div>`;details.classList.remove("hidden");
    document.querySelectorAll(".candidate-node").forEach(button=>button.onclick=()=>{const candidate=result.candidates[Number(button.dataset.candidate)];const node=candidate.nodes[Number(button.dataset.node)];highlightMergeNodes(candidate.nodes);map.setView([node.position[1],node.position[0]],Math.max(map.getZoom(),24));setStatus(`候选来源节点 ${node.node_id}`);});
    document.querySelectorAll(".candidate-use").forEach(button=>button.onclick=()=>previewMerge({node_ids:result.candidates[Number(button.dataset.candidate)].node_ids}));
  }catch(error){setStatus(`无法读取合并候选：${error.message}`);}
}

function showManualMergeSelection() {
  const selected=mergeNodeTokens.map(token=>nodeFeatures.find(feature=>feature.properties.token===token)).filter(Boolean);
  highlightMergeNodes(selected.map(feature=>({position:feature.geometry.coordinates})));
  detailsContent.innerHTML=`<h2>手工合并节点</h2><p>已选择 ${selected.length} 个节点</p><div class="source-options">${selected.map(feature=>`<div class="source-choice">${escapeHtml(feature.properties.node_id)}</div>`).join("")}</div><div class="attribute-actions"><button id="clear-merge" class="secondary-button">清空选择</button><button id="preview-merge" class="primary-button" ${selected.length<2?"disabled":""}>停止选择并检查</button></div>`;details.classList.remove("hidden");
  document.querySelector("#clear-merge").onclick=()=>{mergeNodeTokens=[];openMergeCandidates();clearSelection();};
  document.querySelector("#preview-merge").onclick=()=>previewMerge({node_tokens:mergeNodeTokens});
}

async function previewEdgeDeletion(token) {
  try { const result = await post("/api/delete-edge-preview", {token}); const sources=result.source_segments.map(segment=>`${escapeHtml(segment.source_id)} [${segment.source_start_m.toFixed(2)}, ${segment.source_end_m.toFixed(2)}]${segment.reversed?" 反向":""}`).join("<br>"); showConfirmation("删除派生边", `<dl><dt>边</dt><dd>${escapeHtml(result.edge)}</dd><dt>来源片段</dt><dd>${sources||"无"}</dd><dt>原始数据</dt><dd>SourceEdge 不会被删除</dd></dl>`, "删除派生边", async () => { closeDetails(); try { const response = await post("/api/delete-edge-confirm", {token}, true); setStatus(response.message); } catch(error) { setStatus(`删除失败：${error.message}`); } }); }
  catch(error) { setStatus(`无法删除：${error.message}`); }
}

async function previewNodeDeletion(token) {
  try {
    const result = await post("/api/delete-node-preview", {token});
    const halves=result.half_edges.map(half=>`<div class="source-choice"><strong>${escapeHtml(half.half_id)} · 通向 ${escapeHtml(half.outer_node)}</strong><span>${escapeHtml(half.edge)}</span><span>${escapeHtml(half.source_ids.join(" + "))}</span></div>`).join("");
    const pairs=result.pair_candidates.map(pair=>`<label class="source-option pair-option" data-pair="${pair.pair_id}"><input type="checkbox" name="node-pair" value="${pair.pair_id}" ${pair.recommended?"checked":""}><span><strong>${escapeHtml(pair.endpoints.join(" ↔ "))}</strong><br>${escapeHtml(pair.source_ids.join(" + "))}<br>转角 ${pair.angle_degrees}°${pair.same_source?" · 同源":" · 跨来源"}</span></label>`).join("");
    const unpaired=result.recommended_unpaired.length?`<p class="warning">推荐方案仍有未配对半边：${escapeHtml(result.recommended_unpaired.join(", "))}</p>`:"";
    showConfirmation("删除节点并重组连接", `<p>节点 ${escapeHtml(result.node)} · ${result.half_edges.length} 条关联半边</p><h3>关联半边</h3><div class="source-options">${halves||"<p>无关联边</p>"}</div><h3>选择半边配对</h3><div class="source-options">${pairs||"<p>没有可配对的半边</p>"}</div><p id="pair-stats" class="field-note"></p>${unpaired}<label class="source-option"><input id="discard-unpaired" type="checkbox"><span>明确删除所有未配对半边（可能改变拓扑）</span></label><p class="field-note">同一条半边可以参加多组连接。新边会从有序 SourceSegment 链重建，不会画直线；原始 SourceEdge 不会修改。</p>`, "执行人工重组", async () => {
      const pair_ids=[...document.querySelectorAll('input[name="node-pair"]:checked')].map(input=>input.value); const discard_unpaired=document.querySelector("#discard-unpaired").checked;
      closeDetails(); try { const response=await post("/api/delete-node-confirm", {token,pair_ids,discard_unpaired}, true); setStatus(response.message); } catch(error) { setStatus(`删除失败：${error.message}`); }
    });
    const updatePairStats=()=>{const checked=[...document.querySelectorAll('input[name="node-pair"]:checked')];const used=new Set();checked.forEach(input=>{const pair=result.pair_candidates.find(item=>item.pair_id===input.value);used.add(pair.left);used.add(pair.right);});const missing=result.half_edges.filter(half=>!used.has(half.half_id)).map(half=>half.half_id);document.querySelector("#pair-stats").textContent=`已选择 ${checked.length} 组连接 · 已使用 ${used.size}/${result.half_edges.length} 条半边${missing.length?` · 未使用：${missing.join(", ")}`:" · 无未使用半边"}`;};
    document.querySelectorAll(".pair-option").forEach(label=>{label.onmouseenter=()=>{const pair=result.pair_candidates.find(item=>item.pair_id===label.dataset.pair);showGeometry(pair.geometry,"#db2777");};label.querySelector("input").onchange=updatePairStats;});updatePairStats();
  } catch(error) { setStatus(`无法删除：${error.message}`); }
}

async function previewSplit(token, latlng) {
  const body={edge:token,longitude:latlng.lng,latitude:latlng.lat};
  try {
    const result=await post("/api/split-source-preview",body);
    const choices=result.candidates.map((candidate,index)=>`<label class="source-option"><input type="radio" name="split-node" value="${escapeHtml(candidate.canonical_node_id)}" ${index===0?"checked":""}><span>OSM Node ${escapeHtml(candidate.canonical_node_id)} · 距离 ${candidate.distance_m.toFixed(2)} m</span></label>`).join("");
    const manual=result.candidates.length?"":`<label class="source-option"><input type="radio" name="split-node" value="" checked><span>没有合适 OSM Node，创建负数 ID 人工节点</span></label>`;
    showConfirmation("补充图分割点", `<p class="field-note">在当前派生边中加入一个拓扑节点，并把该边按原始 SourceEdge 曲线切成两段；原始曲线本身不会改变。</p><dl><dt>命中来源</dt><dd>${escapeHtml(result.source_id)}</dd></dl><div class="source-options">${choices}${manual}</div>`, "确认切分", async()=>{
      const selected=document.querySelector('input[name="split-node"]:checked'); const request={...body,osm_node_id:selected.value===""?null:Number(selected.value)};
      closeDetails(); try { const response=await post("/api/split-source-confirm",request,true); setStatus(response.message); } catch(error){setStatus(`切分失败：${error.message}`);}
    });
  } catch(error){setStatus(`无法切分：${error.message}`);}
}

async function previewManualSnap(node, edge) {
  try {
    const result=await post("/api/manual-snap-preview",{node,edge});
    showGeometry(result.connector_geometry,"#db2777");
    showConfirmation("人工吸附预览",`<dl><dt>节点</dt><dd>${escapeHtml(result.node)}</dd><dt>目标边</dt><dd>${escapeHtml(result.edge)}</dd><dt>移动距离</dt><dd>${result.distance_m.toFixed(3)} m</dd><dt>目标来源</dt><dd>${escapeHtml(result.target_source_id)}</dd><dt>来源位置</dt><dd>${result.target_station_m.toFixed(3)} m</dd><dt>原始数据</dt><dd>SourceEdge 不会修改</dd></dl><p class="field-note">确认后会移动图节点、重建它原有的关联边，并在目标来源区间切分派生边。</p>`,"确认人工吸附",async()=>{
      closeDetails();try{const response=await post("/api/manual-snap-confirm",{node,edge},true);firstNode=null;setStatus(response.message);}catch(error){setStatus(`人工吸附失败：${error.message}`);}
    });
  }catch(error){firstNode=null;setStatus(`无法人工吸附：${error.message}`);}
}

function nodeClicked(feature,event) {
  L.DomEvent.stopPropagation(event); const p=feature.properties;
  selectNode(feature);
  if(mode==="delete") return previewNodeDeletion(p.token);
  if(mode==="restore") { if(!firstNode){firstNode=p.token;event.target.setStyle({radius:9,color:"#7e22ce",weight:4});return setStatus(`已选择 ${p.node_id}，请选择另一个 OSM 图节点`);} if(firstNode===p.token)return setStatus("两个端点不能相同"); return previewRestore(firstNode,p.token); }
  if(mode==="snap") { firstNode=p.token;return setStatus(`已选择节点 ${p.node_id}，请点击需要接入的目标派生边`); }
  if(mode==="merge") { if(!mergeNodeTokens.includes(p.token))mergeNodeTokens.push(p.token);showManualMergeSelection();return setStatus(`已选择 ${mergeNodeTokens.length} 个待合并节点`); }
}
function edgeClicked(feature,event) { L.DomEvent.stopPropagation(event); selectEdge(feature); const p=feature.properties; if(mode==="delete")return previewEdgeDeletion(p.token); if(mode==="split")return previewSplit(p.token,event.latlng);if(mode==="snap"){if(!firstNode)return setStatus("请先选择需要人工吸附的图节点");return previewManualSnap(firstNode,p.token);} }

function renderNodes() {
  if(nodeLayer) { layers.removeLayer(nodeLayer); map.removeLayer(nodeLayer); }
  nodeLayer=L.geoJSON({type:"FeatureCollection",features:nodeFeatures},{pane:"nodesPane",pointToLayer:(feature,latlng)=>L.circleMarker(latlng,{pane:"nodesPane",radius:feature.properties.radius,color:"rgba(255,255,255,.9)",fillColor:feature.properties.color,fillOpacity:.9,weight:1.25}),onEachFeature:(feature,layer)=>layer.on("click",event=>nodeClicked(feature,event))});
  nodeLayer.addTo(map); layers.addOverlay(nodeLayer,`图节点 (${nodeFeatures.length})`);
}
function renderEdges(data) {
  if(edgeGroup){layers.removeLayer(edgeGroup);map.removeLayer(edgeGroup);}
  const casing=L.geoJSON(data.edges,{pane:"edgeCasingPane",interactive:false,style:{color:"rgba(255,255,255,.8)",weight:5,opacity:.65}});
  edgeSearchIndex.clear();
  edgeTokenIndex.clear();
  edgeLayer=L.geoJSON(data.edges,{pane:"edgesPane",style:feature=>({color:splitValidation?feature.properties.validation_color:"#9a684d",weight:2.6,opacity:.72}),onEachFeature:(feature,layer)=>{layer.on("click",event=>edgeClicked(feature,event));layer.on("mouseover",()=>layer.setStyle({weight:5,color:"#243746",opacity:.95}));layer.on("mouseout",()=>edgeLayer.resetStyle(layer));const key=edgePairKey(feature.properties.u,feature.properties.v);if(!edgeSearchIndex.has(key))edgeSearchIndex.set(key,[]);edgeSearchIndex.get(key).push({feature,layer});edgeTokenIndex.set(feature.properties.token,{feature,layer});}});
  edgeGroup=L.layerGroup([casing,edgeLayer]).addTo(map); layers.addOverlay(edgeGroup,`派生边 (${data.edge_count})`);
}
function renderReferenceLayers(data) {
  dataLayers.forEach(layer => { layers.removeLayer(layer); map.removeLayer(layer); }); dataLayers=[];
  const flightColors=["#0066cc","#00a878","#7b2cbf","#e76f00","#008c9e","#c03664","#5c7c19","#5f4bb6"];
  const pathColors=["#d00040","#6a00a8","#005f73","#b23a00","#2b6f3e","#8f2d56","#3a0ca3","#9c5700"];
  const dashPatterns=[null,"12 6","3 5","16 5 3 5"];
  data.flights.forEach((collection,index)=>{const color=flightColors[index%flightColors.length];const layer=L.geoJSON(collection,{pane:"flightPane",interactive:false,style:{pane:"flightPane",color:"#fff",weight:7,opacity:.88},pointToLayer:(_feature,latlng)=>L.circleMarker(latlng,{pane:"flightPane",radius:2.5,color:"#fff",fillColor:color,weight:1,fillOpacity:.95})});const accent=L.geoJSON(collection,{pane:"flightPane",interactive:false,filter:feature=>feature.geometry.type!=="Point",style:{pane:"flightPane",color,weight:4.5,opacity:.96,dashArray:dashPatterns[Math.floor(index/flightColors.length)%dashPatterns.length]}});const group=L.layerGroup([layer,accent]);dataLayers.push(group);layers.addOverlay(group,`Flight ${index+1}`);group.addTo(map);});
  data.paths.forEach((collection,index)=>{const color=pathColors[index%pathColors.length];const casing=L.geoJSON(collection,{pane:"pathPane",interactive:false,style:{pane:"pathPane",color:"#fff",weight:9,opacity:.92}});const accent=L.geoJSON(collection,{pane:"pathPane",interactive:false,style:{pane:"pathPane",color,weight:6,opacity:.98,dashArray:dashPatterns[Math.floor(index/pathColors.length)%dashPatterns.length]}});const group=L.layerGroup([casing,accent]);dataLayers.push(group);layers.addOverlay(group,`Path ${index+1}`);group.addTo(map);});
}
async function loadState(){const data=await readResponse(await fetch("/api/state"));currentState=data;renderEdges(data);nodeFeatures=data.nodes.features;nodeFeatureIndex.clear();nodeFeatures.forEach(feature=>nodeFeatureIndex.set(normalizeId(feature.properties.node_id),feature));renderNodes();renderReferenceLayers(data);renderTopologySummary(data.topology);document.querySelector("#counts").textContent=`${data.node_count} 节点 · ${data.edge_count} 边 · ${data.topology.component_count} 分量`;savePath=data.save_path;document.querySelector("#undo").disabled=!data.can_undo;document.querySelector("#finish").classList.toggle("hidden",!data.can_finish);if(!fitted&&nodeLayer.getLayers().length){map.fitBounds(nodeLayer.getBounds(),{padding:[24,24]});fitted=true;}}

function renderTopologySummary(topology) {
  document.querySelector("#topology-summary").innerHTML = [
    [topology.component_count,"连通分量",topology.component_count>1],
    [topology.largest_component,"最大分量节点",false],
    [topology.dangling_count,"度为 1",topology.dangling_count>0],
    [topology.isolated_count,"度为 0",topology.isolated_count>0],
    [topology.parallel_pair_count,"平行边端点组",false]
  ].map(([value,label,alert])=>`<div class="metric ${alert?"alert":""}"><strong>${value}</strong><span>${label}</span></div>`).join("");
}

document.querySelectorAll(".tool").forEach(button=>button.onclick=()=>{document.querySelectorAll(".tool").forEach(item=>item.classList.remove("active"));button.classList.add("active");mode=button.dataset.mode;firstNode=null;mergeNodeTokens=[];closeDetails();setStatus(messages[mode]);if(mode==="merge")openMergeCandidates();});
document.querySelector("#close-details").onclick=closeDetails;
document.querySelector("#search-toggle").onclick=event=>{document.querySelector("#search-panel").classList.toggle("hidden");event.currentTarget.classList.toggle("active");};
document.querySelector("#topology-toggle").onclick=event=>{document.querySelector("#topology-panel").classList.toggle("hidden");event.currentTarget.classList.toggle("active");};
document.querySelectorAll("[data-close]").forEach(button=>button.onclick=()=>{document.querySelector(`#${button.dataset.close}`).classList.add("hidden");});
document.querySelector("#split-validation-toggle").onclick=event=>{splitValidation=!splitValidation;event.currentTarget.classList.toggle("active",splitValidation);event.currentTarget.textContent=splitValidation?"关闭相邻边辨色":"开启相邻边辨色";document.querySelector(".legend").classList.toggle("validation",splitValidation);if(currentState)renderEdges(currentState);setStatus(splitValidation?"拓扑辨色已开启 · 相邻边使用不同颜色，便于检查连接关系":"拓扑辨色已关闭 · 派生边恢复统一颜色");};
document.querySelector("#search-node-button").onclick=()=>{const feature=nodeFeatureIndex.get(normalizeId(document.querySelector("#search-node").value));if(!feature)return setStatus("未找到该节点");selectNode(feature,true);setStatus(`已选中节点 ${feature.properties.node_id}`);};
document.querySelector("#search-edge-button").onclick=()=>{const entries=edgeSearchIndex.get(edgePairKey(document.querySelector("#search-edge-u").value,document.querySelector("#search-edge-v").value));if(!entries?.length)return setStatus("未找到该组端点的派生边");selectEdge(entries[0].feature,true);setStatus(`已选中派生边；该组端点共有 ${entries.length} 条边`);};
document.querySelector("#save").onclick=async()=>{try{const response=await post("/api/save",{},true);setStatus(response.message);}catch(error){setStatus(`保存失败：${error.message}`);}};
document.querySelector("#undo").onclick=async()=>{try{const response=await post("/api/undo",{},true);setStatus(response.message);}catch(error){setStatus(`撤销失败：${error.message}`);}};
document.querySelector("#finish").onclick=async()=>{const result=await readResponse(await fetch("/api/finish",{method:"POST"}));setStatus(result.message);};
document.addEventListener("keydown",event=>{if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==="z"){event.preventDefault();if(!document.querySelector("#undo").disabled)document.querySelector("#undo").click();}});
loadState().catch(error=>setStatus(`载入失败：${error.message}`));
