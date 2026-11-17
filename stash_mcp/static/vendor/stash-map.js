/**
 * Stash Map – force-directed document map (Catppuccin dark theme).
 *
 * Input: {nodes: [{path, title, document}], edges: [{source, target, kind}]}
 * where edge endpoints are node paths and kind is "link" or "embed".
 * Features: canvas rendering, hover highlighting, click to open, drag nodes,
 * scroll zoom, pan, optional focus node, keyboard navigation.
 *
 * Keyboard (canvas focused): arrow keys move between pages, Enter opens the
 * selected page, + and - zoom, 0 fits, Escape clears the selection. Each
 * selection is announced through a live status region. A canvas cannot expose
 * its contents to assistive technology, so the page renders the same pages
 * and links as an ordinary list next to the map; this script only points to it.
 */
(function(){
'use strict';

/* ── colour palette (Catppuccin Mocha) ── */
var C={
  base:'#1e1e2e', mantle:'#181825', surface0:'#313244', surface2:'#585b70',
  overlay1:'#7f849c', overlay2:'#9399b2', text:'#cdd6f4', subtext0:'#a6adc8',
  teal:'#94e2d5', green:'#a6e3a1', blue:'#89b4fa', mauve:'#cba6f7',
  peach:'#fab387', yellow:'#f9e2af', pink:'#f5c2e7', flamingo:'#f2cdcd',
  sky:'#89dceb', lavender:'#b4befe',
};
var FOLDER_COLORS=[C.blue,C.mauve,C.peach,C.green,C.pink,C.sky,C.yellow,C.lavender,C.flamingo];
var LEGEND_MAX=9;

/* ── simulation constants (velocity-Verlet, after d3-force) ── */
var CHARGE=200, LINK_DISTANCE=78, GRAVITY=0.07, VELOCITY_KEEP=0.6, NODE_GAP=16;
var ALPHA_MIN=0.002, ALPHA_DECAY=0.0228, FRAME_BUDGET_MS=10;
var MIN_ZOOM=0.05, MAX_ZOOM=6;

function el(tag,cls,text){
  var e=document.createElement(tag);
  if(cls) e.className=cls;
  if(text!=null) e.textContent=text;
  return e;
}
function basename(path){return path.slice(path.lastIndexOf('/')+1);}
function truncate(s,n){return s.length>n?s.slice(0,n-1)+'…':s;}

function render(root,data,opts){
  opts=opts||{};
  root.innerHTML='';

  /* ── model ── */
  var byPath={};
  var allNodes=data.nodes.map(function(d){
    var slash=d.path.indexOf('/');
    var n={path:d.path, title:d.title, doc:d.document, folder:slash<0?'':d.path.slice(0,slash),
      label:truncate(d.title||basename(d.path),42), x:0, y:0, vx:0, vy:0, degree:0, r:4,
      fixed:false, near:[], out:0, inc:0, color:C.overlay2};
    byPath[d.path]=n;
    return n;
  });
  var allEdges=[];
  data.edges.forEach(function(d){
    var s=byPath[d.source], t=byPath[d.target];
    if(!s||!t||s===t) return;
    allEdges.push({s:s, t:t, embed:d.kind==='embed'});
    s.degree++; t.degree++;
    s.out++; t.inc++;
    s.near.push(t); t.near.push(s);
  });
  allEdges.forEach(function(e){
    e.strength=1/Math.min(e.s.degree,e.t.degree);
    e.bias=e.s.degree/(e.s.degree+e.t.degree);
  });

  /* Colour by top-level folder, busiest folders first so they get distinct hues. */
  var folderCounts={};
  allNodes.forEach(function(n){ if(n.folder) folderCounts[n.folder]=(folderCounts[n.folder]||0)+1; });
  var folders=Object.keys(folderCounts).sort(function(a,b){
    return folderCounts[b]-folderCounts[a]||(a<b?-1:1);
  });
  var folderColor={};
  folders.forEach(function(f,i){ folderColor[f]=FOLDER_COLORS[i%FOLDER_COLORS.length]; });
  allNodes.forEach(function(n,i){
    if(n.folder) n.color=folderColor[n.folder];
    n.r=Math.min(4+Math.sqrt(n.degree)*1.7,15);
    /* Phyllotaxis start: deterministic, evenly spread, no coincident nodes. */
    var radius=12*Math.sqrt(i+0.5), angle=i*2.39996323;
    n.x=radius*Math.cos(angle); n.y=radius*Math.sin(angle);
  });

  var focus=opts.focus?byPath[opts.focus]||null:null;
  var showUnlinked=true;
  var nodes=allNodes, edges=allEdges;

  /* ── DOM ── */
  var canvas=el('canvas','map-canvas');
  /* An application region, so screen readers pass the arrow keys through. */
  canvas.tabIndex=0;
  canvas.setAttribute('role','application');
  canvas.setAttribute('aria-roledescription','document map');
  canvas.setAttribute('aria-label','Document map of '+allNodes.length+' files');
  canvas.textContent='Map of how documents link to each other.';
  var ctx=canvas.getContext('2d');
  root.appendChild(canvas);

  var help=el('div','map-help',
    'Use the arrow keys to move between pages and Enter to open the selected page. '+
    'Plus and minus zoom, zero fits the whole map, and Escape clears the selection. '+
    (opts.listId&&document.getElementById(opts.listId)
      ?'The same pages and links are available as a list after the map.':''));
  help.id='map-help';
  canvas.setAttribute('aria-describedby',help.id);
  root.appendChild(help);

  var legend=el('div','map-legend');
  folders.slice(0,LEGEND_MAX).forEach(function(f){
    var item=el('div','map-legend-item');
    var sw=el('span','map-swatch'); sw.style.background=folderColor[f];
    item.appendChild(sw); item.appendChild(el('span',null,f));
    legend.appendChild(item);
  });
  if(folders.length>LEGEND_MAX){
    legend.appendChild(el('div','map-legend-item','+'+(folders.length-LEGEND_MAX)+' more folders'));
  }
  if(allNodes.some(function(n){return !n.folder;})){
    var topItem=el('div','map-legend-item');
    var topSw=el('span','map-swatch'); topSw.style.background=C.overlay2;
    topItem.appendChild(topSw); topItem.appendChild(el('span',null,'Top level'));
    legend.appendChild(topItem);
  }
  var hasAssets=allNodes.some(function(n){return !n.doc;});
  var hasEmbeds=allEdges.some(function(e){return e.embed;});
  if(legend.children.length&&(hasAssets||hasEmbeds)) legend.appendChild(el('div','map-legend-rule'));
  if(hasAssets){
    var assetItem=el('div','map-legend-item');
    assetItem.appendChild(el('span','map-swatch hollow'));
    assetItem.appendChild(el('span',null,'Other file'));
    legend.appendChild(assetItem);
  }
  if(hasEmbeds) legend.appendChild(el('div','map-legend-item','┄┄ Embed'));
  if(legend.children.length) root.appendChild(legend);

  var controls=el('div','map-controls');
  var toggleLabel=el('label');
  var toggle=el('input'); toggle.type='checkbox'; toggle.checked=true;
  toggleLabel.appendChild(toggle);
  toggleLabel.appendChild(document.createTextNode('Unlinked pages'));
  var fitButton=el('button',null,'Fit'); fitButton.type='button';
  if(allNodes.some(function(n){return n.degree===0;})) controls.appendChild(toggleLabel);
  controls.appendChild(fitButton);
  root.appendChild(controls);

  var HINT='Scroll to zoom \u00b7 drag to pan \u00b7 click a page to open it';
  var KEY_HINT='Arrow keys move between pages \u00b7 Enter opens \u00b7 + and \u2212 zoom \u00b7 0 fits';
  var status=el('div','map-status',HINT);
  status.setAttribute('role','status');
  status.setAttribute('aria-live','polite');
  root.appendChild(status);

  /* ── view ── */
  var width=0, height=0, dpr=1;
  var view={x:0, y:0, k:1};
  var autoFit=true;     // follow the layout until the reader takes over
  var hover=null, dragNode=null, panning=false, moved=false, last=null;
  /* The pointer and the keyboard can each pick a page. One page is "current"
     at a time — see current() — and it is the one that is highlighted, named
     in the status line, and opened by Enter, so those never disagree. Taking
     up the arrow keys drops any hover left behind by a resting pointer. */
  var selected=null;    // the page keyboard navigation is on
  var keyboard=false;   // true while the canvas is being driven by keys
  var alpha=1, alphaTarget=0, running=false, drawQueued=false;

  function resize(){
    width=root.clientWidth; height=root.clientHeight;
    dpr=window.devicePixelRatio||1;
    canvas.width=Math.max(1,Math.round(width*dpr));
    canvas.height=Math.max(1,Math.round(height*dpr));
    if(autoFit) fit();
    requestDraw();
  }

  function fit(){
    if(!nodes.length||!width||!height) return;
    var x0=Infinity,y0=Infinity,x1=-Infinity,y1=-Infinity;
    nodes.forEach(function(n){
      if(n.x-n.r<x0) x0=n.x-n.r; if(n.x+n.r>x1) x1=n.x+n.r;
      if(n.y-n.r<y0) y0=n.y-n.r; if(n.y+n.r>y1) y1=n.y+n.r;
    });
    /* Leave room for labels to the right and the overlays at the edges. */
    var padX=90, padY=56;
    var k=Math.min((width-2*padX)/Math.max(x1-x0,1),(height-2*padY)/Math.max(y1-y0,1),1.6);
    k=Math.max(k,MIN_ZOOM);
    view.k=k;
    view.x=width/2-k*(x0+x1)/2;
    view.y=height/2-k*(y0+y1)/2;
  }

  /* ── simulation ── */
  function tick(){
    var n=nodes.length,i,j,a,b,dx,dy,d2,f,e,d,gap;
    alpha+=(alphaTarget-alpha)*ALPHA_DECAY;
    for(i=0;i<n;i++){
      a=nodes[i];
      for(j=i+1;j<n;j++){
        b=nodes[j];
        dx=b.x-a.x; dy=b.y-a.y; d2=dx*dx+dy*dy;
        if(d2<1){dx=0.5+(i%3)*0.1; dy=0.5-(j%3)*0.1; d2=1;}
        f=CHARGE*alpha/d2;
        a.vx-=dx*f; a.vy-=dy*f; b.vx+=dx*f; b.vy+=dy*f;
        /* Collision: pages that share neighbours get pulled onto each
           other by their links, so keep a minimum gap between any two. */
        gap=a.r+b.r+NODE_GAP;
        if(d2<gap*gap){
          f=(gap-Math.sqrt(d2))/Math.sqrt(d2)*0.35;
          a.vx-=dx*f; a.vy-=dy*f; b.vx+=dx*f; b.vy+=dy*f;
        }
      }
    }
    for(i=0;i<edges.length;i++){
      e=edges[i];
      dx=e.t.x+e.t.vx-e.s.x-e.s.vx; dy=e.t.y+e.t.vy-e.s.y-e.s.vy;
      d=Math.sqrt(dx*dx+dy*dy)||1;
      f=(d-LINK_DISTANCE)/d*alpha*e.strength;
      dx*=f; dy*=f;
      e.t.vx-=dx*e.bias; e.t.vy-=dy*e.bias;
      e.s.vx+=dx*(1-e.bias); e.s.vy+=dy*(1-e.bias);
    }
    for(i=0;i<n;i++){
      a=nodes[i];
      if(a.fixed){a.vx=0; a.vy=0; continue;}
      a.vx=(a.vx-a.x*GRAVITY*alpha)*VELOCITY_KEEP;
      a.vy=(a.vy-a.y*GRAVITY*alpha)*VELOCITY_KEEP;
      a.x+=a.vx; a.y+=a.vy;
    }
  }

  function settled(){return alpha<ALPHA_MIN&&alphaTarget===0;}

  function frame(){
    var start=performance.now();
    do{ tick(); }while(!settled()&&performance.now()-start<FRAME_BUDGET_MS);
    if(autoFit) fit();
    draw();
    if(settled()) running=false;
    else requestAnimationFrame(frame);
  }
  function wake(reheat){
    if(reheat&&alpha<reheat) alpha=reheat;
    if(!running){running=true; requestAnimationFrame(frame);}
  }
  function requestDraw(){
    if(running||drawQueued) return;
    drawQueued=true;
    requestAnimationFrame(function(){drawQueued=false; draw();});
  }

  /* ── drawing ── */
  function draw(){
    var k=view.k, i, e, n;
    /* A hovered page dims everything but its neighbourhood. The focused
       page is only marked — ring, teal links, labels — so the rest of the
       map stays readable while exploring from it. */
    var hot=current();
    var mark=hot||focus;
    if(mark&&nodes.indexOf(mark)<0){ hot=null; mark=null; }
    var marked=null;
    if(mark){ marked=new Set(mark.near); marked.add(mark); }

    ctx.setTransform(dpr,0,0,dpr,0,0);
    ctx.clearRect(0,0,width,height);
    ctx.translate(view.x,view.y);
    ctx.scale(k,k);

    for(i=0;i<edges.length;i++){
      e=edges[i];
      var on=mark&&(e.s===mark||e.t===mark);
      ctx.strokeStyle=on?C.teal:C.overlay1;
      ctx.fillStyle=ctx.strokeStyle;
      ctx.globalAlpha=on?0.95:(hot?0.12:0.4);
      ctx.lineWidth=(on?1.6:1)/k;
      drawEdge(e,k);
    }
    ctx.setLineDash([]);

    for(i=0;i<nodes.length;i++){
      n=nodes[i];
      ctx.globalAlpha=hot&&!marked.has(n)?0.22:1;
      ctx.beginPath();
      /* Never smaller than a couple of pixels, however far zoomed out. */
      ctx.arc(n.x,n.y,Math.max(n.r,2.2/k),0,6.2832);
      if(n.doc){
        ctx.fillStyle=n.color; ctx.fill();
      }else{
        ctx.fillStyle=C.mantle; ctx.fill();
        ctx.strokeStyle=n.color; ctx.lineWidth=1.5; ctx.stroke();
      }
      if(n===focus){
        ctx.beginPath();
        ctx.arc(n.x,n.y,n.r+4/k,0,6.2832);
        ctx.strokeStyle=C.teal; ctx.lineWidth=2/k; ctx.stroke();
      }
      if(keyboard&&n===selected){
        /* Keyboard position: a second, brighter ring outside any focus ring. */
        ctx.globalAlpha=1;
        ctx.beginPath();
        ctx.arc(n.x,n.y,n.r+(n===focus?8:4)/k,0,6.2832);
        ctx.strokeStyle=C.text; ctx.lineWidth=2/k; ctx.stroke();
      }
    }

    /* Labels: everything when the map is small or zoomed in, otherwise only
       the highlighted neighbourhood. Drawn at a constant on-screen size. */
    var labelAll=nodes.length<=60||k>=1.3;
    ctx.font=(12/k)+'px -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif';
    ctx.textBaseline='middle';
    ctx.lineJoin='round';
    for(i=0;i<nodes.length;i++){
      n=nodes[i];
      if(!(marked&&marked.has(n))&&(!labelAll||hot)) continue;
      ctx.globalAlpha=1;
      ctx.lineWidth=3/k; ctx.strokeStyle=C.mantle;
      ctx.strokeText(n.label,n.x+n.r+5/k,n.y);
      ctx.fillStyle=n===mark?C.teal:C.text;
      ctx.fillText(n.label,n.x+n.r+5/k,n.y);
    }
    ctx.globalAlpha=1;
  }

  function drawEdge(e,k){
    var dx=e.t.x-e.s.x, dy=e.t.y-e.s.y;
    var d=Math.sqrt(dx*dx+dy*dy);
    if(d<=e.s.r+e.t.r) return;
    var ux=dx/d, uy=dy/d;
    var head=Math.min(6/k,9);
    var x0=e.s.x+ux*e.s.r, y0=e.s.y+uy*e.s.r;
    var x1=e.t.x-ux*(e.t.r+1/k), y1=e.t.y-uy*(e.t.r+1/k);
    ctx.setLineDash(e.embed?[4/k,3/k]:[]);
    ctx.beginPath();
    ctx.moveTo(x0,y0);
    ctx.lineTo(x1-ux*head*0.8,y1-uy*head*0.8);
    ctx.stroke();
    /* Arrowhead points at the referenced file. */
    ctx.beginPath();
    ctx.moveTo(x1,y1);
    ctx.lineTo(x1-ux*head-uy*head*0.45,y1-uy*head+ux*head*0.45);
    ctx.lineTo(x1-ux*head+uy*head*0.45,y1-uy*head-ux*head*0.45);
    ctx.closePath();
    ctx.fill();
  }

  /* ── interaction ── */
  function localPoint(ev){
    var rect=canvas.getBoundingClientRect();
    return {x:ev.clientX-rect.left, y:ev.clientY-rect.top};
  }
  function nodeAt(pt){
    var wx=(pt.x-view.x)/view.k, wy=(pt.y-view.y)/view.k;
    var slack=5/view.k, best=null, bestD=Infinity;
    for(var i=0;i<nodes.length;i++){
      var n=nodes[i], dx=n.x-wx, dy=n.y-wy, d=dx*dx+dy*dy, reach=n.r+slack;
      if(d<=reach*reach&&d<bestD){best=n; bestD=d;}
    }
    return best;
  }
  function current(){ return dragNode||hover||(keyboard?selected:null); }
  function refreshStatus(){
    var n=current();
    status.textContent='';
    if(n){
      status.appendChild(el('strong',null,n.title||basename(n.path)));
      status.appendChild(document.createTextNode(
        '  '+n.path+' \u00b7 links to '+n.out+' \u00b7 linked from '+n.inc));
    }else{
      status.textContent=keyboard?KEY_HINT:HINT;
    }
  }
  function setHover(n){
    if(n===hover) return;
    hover=n;
    canvas.style.cursor=n?'pointer':'';
    refreshStatus();
    requestDraw();
  }
  function useKeyboard(){
    keyboard=true;
    hover=null;
    canvas.style.cursor='';
  }
  function open(n,ev){
    var url='/ui/browse/'+n.path.split('/').map(encodeURIComponent).join('/');
    if(ev.metaKey||ev.ctrlKey) window.open(url,'_blank');
    else window.location.href=url;
  }

  canvas.addEventListener('pointerdown',function(ev){
    if(ev.button!==0) return;
    last=localPoint(ev); moved=false;
    dragNode=nodeAt(last);
    panning=!dragNode;
    try{ canvas.setPointerCapture(ev.pointerId); }catch(err){ /* pointer already gone */ }
  });
  canvas.addEventListener('pointermove',function(ev){
    var pt=localPoint(ev);
    if(!dragNode&&!panning){ setHover(nodeAt(pt)); return; }
    if(!moved&&Math.abs(pt.x-last.x)+Math.abs(pt.y-last.y)<4) return;
    moved=true; autoFit=false;
    if(dragNode){
      dragNode.fixed=true;
      dragNode.x=(pt.x-view.x)/view.k; dragNode.y=(pt.y-view.y)/view.k;
      alphaTarget=0.3; wake();
    }else{
      view.x+=pt.x-last.x; view.y+=pt.y-last.y;
      canvas.style.cursor='grabbing';
      requestDraw();
    }
    last=pt;
  });
  function release(ev){
    var n=dragNode, wasClick=!moved;
    if(n) n.fixed=false;
    dragNode=null; panning=false; alphaTarget=0;
    canvas.style.cursor=hover?'pointer':'';
    if(n&&wasClick&&ev.type==='pointerup') open(n,ev);
    else requestDraw();
  }
  canvas.addEventListener('pointerup',release);
  canvas.addEventListener('pointercancel',release);
  canvas.addEventListener('pointerleave',function(){ if(!dragNode&&!panning) setHover(null); });
  canvas.addEventListener('wheel',function(ev){
    ev.preventDefault();
    var pt=localPoint(ev);
    var k=Math.min(MAX_ZOOM,Math.max(MIN_ZOOM,view.k*Math.exp(-ev.deltaY*0.0015)));
    view.x=pt.x-(pt.x-view.x)*k/view.k;
    view.y=pt.y-(pt.y-view.y)*k/view.k;
    view.k=k; autoFit=false;
    requestDraw();
  },{passive:false});

  /* ── keyboard ── */
  function present(n){ return n&&nodes.indexOf(n)>=0; }
  /* Start from the focused page, else whichever page is nearest the middle. */
  function startNode(){
    if(present(focus)) return focus;
    var cx=(width/2-view.x)/view.k, cy=(height/2-view.y)/view.k, best=null, bestD=Infinity;
    nodes.forEach(function(n){
      var d=(n.x-cx)*(n.x-cx)+(n.y-cy)*(n.y-cy);
      if(d<bestD){best=n; bestD=d;}
    });
    return best;
  }
  /* Pan just enough to bring a page on screen; leave the view alone otherwise. */
  function reveal(n){
    var sx=n.x*view.k+view.x, sy=n.y*view.k+view.y, pad=48;
    if(sx>=pad&&sx<=width-pad&&sy>=pad&&sy<=height-pad) return;
    view.x+=width/2-sx; view.y+=height/2-sy;
    autoFit=false;
  }
  function select(n){
    selected=n||null;
    if(selected) reveal(selected);
    refreshStatus();
    requestDraw();
  }
  /* Move to the nearest page in a direction, preferring ones close to that
     axis so that repeated presses travel in a line rather than zig-zagging. */
  function step(dx,dy){
    if(!present(selected)){ select(startNode()); return; }
    var best=null, bestScore=Infinity;
    nodes.forEach(function(n){
      if(n===selected) return;
      var vx=n.x-selected.x, vy=n.y-selected.y;
      var along=vx*dx+vy*dy, across=vx*dy-vy*dx;
      if(along<=0) return;
      var score=along*along+4*across*across;
      if(score<bestScore){best=n; bestScore=score;}
    });
    if(best) select(best);
  }
  function zoomBy(factor){
    var anchor=present(selected)&&keyboard
      ?{x:selected.x*view.k+view.x, y:selected.y*view.k+view.y}
      :{x:width/2, y:height/2};
    var k=Math.min(MAX_ZOOM,Math.max(MIN_ZOOM,view.k*factor));
    view.x=anchor.x-(anchor.x-view.x)*k/view.k;
    view.y=anchor.y-(anchor.y-view.y)*k/view.k;
    view.k=k; autoFit=false;
    requestDraw();
  }
  canvas.addEventListener('focus',function(){
    /* Only a keyboard arrival selects a page; a click should not. */
    if(canvas.matches(':focus-visible')) useKeyboard();
    if(keyboard&&!present(selected)) selected=startNode();
    if(keyboard&&selected) reveal(selected);
    refreshStatus();
    requestDraw();
  });
  canvas.addEventListener('blur',function(){
    keyboard=false;
    refreshStatus();
    requestDraw();
  });
  canvas.addEventListener('keydown',function(ev){
    var key=ev.key;
    if(key==='Enter'){
      var target=current();
      if(keyboard&&!dragNode&&present(target)){ ev.preventDefault(); open(target,ev); }
      return;
    }
    if(ev.metaKey||ev.ctrlKey||ev.altKey) return;   // leave browser shortcuts alone
    var arrows={ArrowRight:[1,0], ArrowLeft:[-1,0], ArrowDown:[0,1], ArrowUp:[0,-1]};
    if(arrows[key]){ useKeyboard(); step(arrows[key][0],arrows[key][1]); }
    else if(key==='+'||key==='='){ zoomBy(1.25); }
    else if(key==='-'||key==='_'){ zoomBy(0.8); }
    else if(key==='0'){ autoFit=true; fit(); requestDraw(); }
    else if(key==='Escape'){ select(null); }
    else return;
    ev.preventDefault();
  });

  fitButton.addEventListener('click',function(){ autoFit=true; fit(); requestDraw(); });
  toggle.addEventListener('change',function(){
    showUnlinked=toggle.checked;
    nodes=showUnlinked?allNodes:allNodes.filter(function(n){return n.degree>0;});
    if(hover&&nodes.indexOf(hover)<0) setHover(null);
    if(selected&&nodes.indexOf(selected)<0) select(null);
    autoFit=true;
    wake(0.5);
  });

  if(window.ResizeObserver) new ResizeObserver(resize).observe(root);
  else window.addEventListener('resize',resize);
  resize();
  wake();

  return {
    fit:function(){ autoFit=true; fit(); requestDraw(); },
    nodes:function(){ return nodes; },
    view:function(){ return view; },
    selected:function(){ return keyboard?selected:null; },
    settled:settled,
  };
}

window.StashMap={render:render};
})();
