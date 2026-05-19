/**
 * Stash Gantt – interactive Gantt chart renderer (Catppuccin dark theme).
 *
 * Input: pre-parsed JS object {title, sections: [{name, tasks: [{id, title, start, duration|end, depends?}]}]}
 * Features: SVG rendering, hover tooltips, click-to-select, drag to reschedule, scroll zoom, pan.
 */
(function(){
'use strict';

/* ── colour palette (Catppuccin Mocha) ── */
var C={
  base:'#1e1e2e', mantle:'#181825', crust:'#11111b',
  surface0:'#313244', surface1:'#45475a', surface2:'#585b70',
  overlay0:'#6c7086', overlay1:'#7f849c', overlay2:'#9399b2',
  text:'#cdd6f4', subtext0:'#a6adc8', subtext1:'#bac2de',
  teal:'#94e2d5', green:'#a6e3a1', blue:'#89b4fa', mauve:'#cba6f7',
  peach:'#fab387', yellow:'#f9e2af', red:'#f38ba8', pink:'#f5c2e7',
  flamingo:'#f2cdcd', rosewater:'#f5e0dc', sky:'#89dceb', lavender:'#b4befe',
};
var BAR_COLORS=[C.teal,C.blue,C.mauve,C.peach,C.green,C.pink,C.sky,C.lavender,C.yellow,C.flamingo];

/* ── date helpers ── */
function parseDate(s){
  if(s instanceof Date) return s;
  var d=new Date(s);
  if(isNaN(d.getTime())) throw new Error('Invalid date: '+s);
  return d;
}
function addDays(d,n){var r=new Date(d);r.setDate(r.getDate()+n);return r;}
function diffDays(a,b){return Math.round((b-a)/(864e5));}
function fmtDate(d){
  var mon=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  return mon[d.getMonth()]+' '+d.getDate()+', '+d.getFullYear();
}
function fmtShort(d){
  var mon=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  return mon[d.getMonth()]+' '+d.getDate();
}
function parseDuration(s){
  if(typeof s==='number') return s;
  var m=String(s).match(/^(\d+)\s*d$/i);
  return m?parseInt(m[1],10):parseInt(s,10)||1;
}
function toYAMLDate(d){
  var y=d.getFullYear(), m=String(d.getMonth()+1).padStart(2,'0'), dd=String(d.getDate()).padStart(2,'0');
  return y+'-'+m+'-'+dd;
}

/* ── serialise back to YAML ── */
function toYAML(data){
  var out=[];
  if(data.title) out.push('title: '+data.title);
  if(data.sections){
    out.push('sections:');
    data.sections.forEach(function(sec){
      out.push('  - name: '+sec.name);
      out.push('    tasks:');
      sec.tasks.forEach(function(t){
        out.push('      - id: '+t.id);
        out.push('        title: "'+t.title.replace(/"/g,'\\"')+'"');
        out.push('        start: '+toYAMLDate(t._start));
        out.push('        duration: '+diffDays(t._start,t._end)+'d');
        if(t.depends) out.push('        depends: '+t.depends);
      });
    });
  }
  return out.join('\n')+'\n';
}

/* ── resolve tasks from parsed data ── */
function resolveTasks(data){
  var sections=data.sections||[];
  var taskMap={};var allTasks=[];var minD=null,maxD=null;
  sections.forEach(function(sec,si){
    var tasks=sec.tasks||[];
    tasks.forEach(function(t){
      var start=parseDate(t.start);
      var end;
      if(t.end){end=parseDate(t.end);}
      else if(t.duration){end=addDays(start,parseDuration(t.duration));}
      else{end=addDays(start,7);}
      var resolved={id:t.id||('t'+allTasks.length),title:t.title||'Untitled',
        _start:start,_end:end,section:sec.name,sectionIdx:si,
        depends:t.depends||null,color:BAR_COLORS[si%BAR_COLORS.length]};
      taskMap[resolved.id]=resolved;
      allTasks.push(resolved);
      if(!minD||start<minD)minD=start;
      if(!maxD||end>maxD)maxD=end;
    });
  });
  if(!minD){minD=new Date();maxD=addDays(minD,30);}
  return {sections:sections,tasks:allTasks,taskMap:taskMap,minDate:addDays(minD,-3),maxDate:addDays(maxD,3)};
}

/* ── main render ── */
window.StashGantt={
  render:function(container,data,opts){
    opts=opts||{};
    var savePath=opts.savePath||null;
    var readOnly=opts.readOnly||false;
    if(!data||!data.sections){
      container.innerHTML='<div style="color:'+C.red+';padding:1rem">Invalid gantt data: missing sections</div>';
      return;
    }
    var resolved=resolveTasks(data);
    var state={
      data:data, resolved:resolved,
      viewMin:resolved.minDate, viewMax:resolved.maxDate,
      selected:null, dragging:null, dragStartX:0, dragOrigStart:null,
      panning:false, panStartX:0, panViewMin:null, panViewMax:null,
      dirty:false
    };

    var ROW_H=40, HEADER_H=60, SECTION_H=28, LABEL_W=180, PAD=16;
    var totalRows=0;
    resolved.sections.forEach(function(sec){totalRows++;totalRows+=(sec.tasks||[]).length;});
    var chartH=HEADER_H+totalRows*ROW_H+PAD;

    container.innerHTML='';
    container.style.position='relative';

    /* toolbar */
    var toolbar=document.createElement('div');
    toolbar.className='gantt-toolbar';
    toolbar.innerHTML=
      '<span class="gantt-title">'+(data.title||'Gantt Chart')+'</span>'+
      '<span class="gantt-hint">Scroll to zoom • Drag background to pan'+(readOnly?'':'  • Drag bars to reschedule')+'</span>'+
      (!readOnly&&savePath?'<button class="gantt-save-btn" disabled>Save changes</button>':'');
    container.appendChild(toolbar);

    var saveBtn=toolbar.querySelector('.gantt-save-btn');

    /* svg container for scroll */
    var wrap=document.createElement('div');
    wrap.className='gantt-scroll-wrap';
    container.appendChild(wrap);

    var svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
    wrap.appendChild(svg);

    /* tooltip */
    var tip=document.createElement('div');
    tip.className='gantt-tooltip';
    tip.style.display='none';
    container.appendChild(tip);

    function draw(){
      var W=wrap.offsetWidth||800;
      var chartW=W;
      svg.setAttribute('width',chartW);
      svg.setAttribute('height',chartH);
      svg.setAttribute('viewBox','0 0 '+chartW+' '+chartH);
      svg.innerHTML='';

      var timeW=chartW-LABEL_W-PAD;
      var viewSpan=state.viewMax-state.viewMin;
      function xForDate(d){return LABEL_W+((d-state.viewMin)/viewSpan)*timeW;}
      state._xForDate=xForDate;
      state._dateForX=function(x){return new Date(state.viewMin.getTime()+((x-LABEL_W)/timeW)*viewSpan);};
      state._timeW=timeW;

      /* background */
      var bg=el('rect',{x:0,y:0,width:chartW,height:chartH,fill:C.mantle,rx:6});
      svg.appendChild(bg);

      /* time axis */
      var daySpan=diffDays(state.viewMin,state.viewMax);
      var tickDays=daySpan<=30?7:daySpan<=90?14:30;
      var axisY=HEADER_H-10;
      var d=new Date(state.viewMin);
      d.setDate(d.getDate()-(d.getDay()||7)+1);
      while(d<=state.viewMax){
        var x=xForDate(d);
        if(x>=LABEL_W&&x<=chartW){
          svg.appendChild(el('line',{x1:x,y1:HEADER_H,x2:x,y2:chartH,stroke:C.surface0,'stroke-width':1,'stroke-dasharray':'2,4'}));
          svg.appendChild(elText(fmtShort(d),x,axisY,{fill:C.overlay1,'font-size':'11px','text-anchor':'middle'}));
        }
        d=addDays(d,tickDays);
      }

      /* today marker */
      var today=new Date();today.setHours(0,0,0,0);
      var todayX=xForDate(today);
      if(todayX>=LABEL_W&&todayX<=chartW){
        svg.appendChild(el('line',{x1:todayX,y1:HEADER_H,x2:todayX,y2:chartH,stroke:C.red,'stroke-width':1.5,opacity:0.6}));
        svg.appendChild(elText('Today',todayX,HEADER_H-22,{fill:C.red,'font-size':'10px','text-anchor':'middle','font-weight':'600'}));
      }

      /* rows */
      var y=HEADER_H;
      resolved.sections.forEach(function(sec,si){
        /* section header row */
        svg.appendChild(el('rect',{x:0,y:y,width:chartW,height:SECTION_H,fill:C.surface0,opacity:0.5}));
        svg.appendChild(elText(sec.name,12,y+SECTION_H/2+4,{fill:C.subtext1,'font-size':'12px','font-weight':'600','text-transform':'uppercase','letter-spacing':'0.5px'}));
        y+=SECTION_H;

        (sec.tasks||[]).forEach(function(t){
          var task=state.resolved.taskMap[t.id||''];
          if(!task){y+=ROW_H;return;}

          /* row stripe */
          var rowIdx=Math.floor((y-HEADER_H)/ROW_H);
          if(rowIdx%2===0){
            svg.appendChild(el('rect',{x:0,y:y,width:chartW,height:ROW_H,fill:C.surface0,opacity:0.15}));
          }

          /* label */
          svg.appendChild(elText(task.title,PAD,y+ROW_H/2+4,{fill:C.text,'font-size':'13px',class:'gantt-label'}));

          /* bar */
          var x1=xForDate(task._start), x2=xForDate(task._end);
          var barW=Math.max(x2-x1,4);
          var barY=y+8, barH=ROW_H-16;
          var isSelected=state.selected===task.id;

          var barG=elG({class:'gantt-bar','data-id':task.id,cursor:readOnly?'pointer':'grab'});

          /* bar shadow */
          barG.appendChild(el('rect',{x:x1+1,y:barY+2,width:barW,height:barH,rx:4,fill:'#000',opacity:0.2}));
          /* bar fill */
          barG.appendChild(el('rect',{x:x1,y:barY,width:barW,height:barH,rx:4,fill:task.color,opacity:isSelected?1:0.85,stroke:isSelected?C.text:'none','stroke-width':isSelected?2:0}));
          /* bar text */
          if(barW>50){
            barG.appendChild(elText(task.title,x1+8,barY+barH/2+4,{fill:C.crust,'font-size':'12px','font-weight':'600',class:'gantt-bar-text'}));
          }
          /* progress indicator: date range on bar */
          if(barW>100){
            var dStr=diffDays(task._start,task._end)+'d';
            barG.appendChild(elText(dStr,x2-8,barY+barH/2+4,{fill:C.crust,'font-size':'10px','text-anchor':'end',opacity:0.7}));
          }

          svg.appendChild(barG);
          y+=ROW_H;
        });
      });

      /* dependency arrows */
      resolved.tasks.forEach(function(task){
        if(!task.depends)return;
        var dep=state.resolved.taskMap[task.depends];
        if(!dep)return;
        var fromX=xForDate(dep._end), fromY=0, toX=xForDate(task._start), toY=0;
        /* find Y positions */
        var cy=HEADER_H;
        resolved.sections.forEach(function(sec){
          cy+=SECTION_H;
          (sec.tasks||[]).forEach(function(t){
            var tid=t.id||'';
            if(tid===dep.id) fromY=cy+ROW_H/2;
            if(tid===task.id) toY=cy+ROW_H/2;
            cy+=ROW_H;
          });
        });
        if(fromY&&toY){
          var midX=fromX+(toX-fromX)/2;
          var path='M'+fromX+' '+fromY+' C'+midX+' '+fromY+' '+midX+' '+toY+' '+toX+' '+toY;
          svg.appendChild(el('path',{d:path,fill:'none',stroke:C.overlay0,'stroke-width':1.5,'marker-end':'url(#arrow)'}));
        }
      });

      /* arrow marker def */
      var defs=document.createElementNS('http://www.w3.org/2000/svg','defs');
      defs.innerHTML='<marker id="arrow" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="'+C.overlay0+'"/></marker>';
      svg.appendChild(defs);
    }

    /* ── events ── */

    /* hover tooltip */
    svg.addEventListener('mousemove',function(e){
      var bar=e.target.closest('.gantt-bar');
      if(!bar){tip.style.display='none';return;}
      var id=bar.getAttribute('data-id');
      var task=state.resolved.taskMap[id];
      if(!task){tip.style.display='none';return;}
      var days=diffDays(task._start,task._end);
      tip.innerHTML='<strong>'+task.title+'</strong><br>'+
        '<span class="gantt-tip-section">'+task.section+'</span><br>'+
        fmtDate(task._start)+' → '+fmtDate(task._end)+'<br>'+
        '<span class="gantt-tip-dur">'+days+' day'+(days!==1?'s':'')+'</span>';
      tip.style.display='block';
      var rect=container.getBoundingClientRect();
      var tx=e.clientX-rect.left+12, ty=e.clientY-rect.top-10;
      if(tx+200>rect.width)tx=e.clientX-rect.left-210;
      tip.style.left=tx+'px';tip.style.top=ty+'px';
    });
    svg.addEventListener('mouseleave',function(){tip.style.display='none';});

    /* click to select */
    svg.addEventListener('click',function(e){
      var bar=e.target.closest('.gantt-bar');
      if(bar){
        state.selected=bar.getAttribute('data-id');
      }else{
        state.selected=null;
      }
      draw();
    });

    /* drag to reschedule */
    if(!readOnly){
      svg.addEventListener('mousedown',function(e){
        var bar=e.target.closest('.gantt-bar');
        if(bar){
          e.preventDefault();
          var id=bar.getAttribute('data-id');
          var task=state.resolved.taskMap[id];
          if(!task)return;
          state.dragging=id;
          state.dragStartX=e.clientX;
          state.dragOrigStart=new Date(task._start);
          state.dragOrigEnd=new Date(task._end);
          state.selected=id;
          svg.style.cursor='grabbing';
          draw();
          return;
        }
        /* pan on background */
        state.panning=true;
        state.panStartX=e.clientX;
        state.panViewMin=new Date(state.viewMin);
        state.panViewMax=new Date(state.viewMax);
        svg.style.cursor='move';
      });
    }else{
      svg.addEventListener('mousedown',function(e){
        state.panning=true;
        state.panStartX=e.clientX;
        state.panViewMin=new Date(state.viewMin);
        state.panViewMax=new Date(state.viewMax);
        svg.style.cursor='move';
      });
    }

    document.addEventListener('mousemove',function(e){
      if(state.dragging){
        var dx=e.clientX-state.dragStartX;
        var msPerPx=(state.viewMax-state.viewMin)/state._timeW;
        var dayShift=Math.round((dx*msPerPx)/864e5);
        var task=state.resolved.taskMap[state.dragging];
        if(task){
          task._start=addDays(state.dragOrigStart,dayShift);
          task._end=addDays(state.dragOrigEnd,dayShift);
          draw();
        }
      }
      if(state.panning){
        var dx2=e.clientX-state.panStartX;
        var msPerPx2=(state.panViewMax-state.panViewMin)/state._timeW;
        var shift=dx2*msPerPx2;
        state.viewMin=new Date(state.panViewMin.getTime()-shift);
        state.viewMax=new Date(state.panViewMax.getTime()-shift);
        draw();
      }
    });

    document.addEventListener('mouseup',function(){
      if(state.dragging){
        state.dirty=true;
        if(saveBtn)saveBtn.disabled=false;
        state.dragging=null;
        svg.style.cursor='';
      }
      if(state.panning){
        state.panning=false;
        svg.style.cursor='';
      }
    });

    /* scroll to zoom */
    wrap.addEventListener('wheel',function(e){
      e.preventDefault();
      var zoomFactor=e.deltaY>0?1.15:0.87;
      var rect=wrap.getBoundingClientRect();
      var mouseX=e.clientX-rect.left;
      var ratio=(mouseX-LABEL_W)/state._timeW;
      if(ratio<0)ratio=0;if(ratio>1)ratio=1;

      var span=state.viewMax-state.viewMin;
      var newSpan=span*zoomFactor;
      var minSpan=7*864e5;var maxSpan=365*3*864e5;
      if(newSpan<minSpan)newSpan=minSpan;
      if(newSpan>maxSpan)newSpan=maxSpan;

      var pivot=state.viewMin.getTime()+span*ratio;
      state.viewMin=new Date(pivot-newSpan*ratio);
      state.viewMax=new Date(pivot+newSpan*(1-ratio));
      draw();
    },{passive:false});

    /* save button */
    if(saveBtn&&savePath){
      saveBtn.addEventListener('click',function(){
        /* rebuild YAML from current task positions */
        var newData=JSON.parse(JSON.stringify(data));
        newData.sections.forEach(function(sec){
          (sec.tasks||[]).forEach(function(t){
            var task=state.resolved.taskMap[t.id];
            if(task){
              t.start=toYAMLDate(task._start);
              t.duration=diffDays(task._start,task._end)+'d';
              delete t.end;
            }
          });
        });
        var yaml=toYAML(newData);
        var form=new FormData();
        form.append('path',savePath);
        form.append('content',yaml);
        fetch('/ui/save',{method:'POST',body:form,redirect:'manual'}).then(function(){
          state.dirty=false;
          saveBtn.disabled=true;
          saveBtn.textContent='Saved!';
          setTimeout(function(){saveBtn.textContent='Save changes';},2000);
        }).catch(function(err){
          saveBtn.textContent='Error saving';
          setTimeout(function(){saveBtn.textContent='Save changes';saveBtn.disabled=false;},3000);
        });
      });
    }

    /* ── SVG helpers ── */
    function el(tag,attrs){
      var e=document.createElementNS('http://www.w3.org/2000/svg',tag);
      for(var k in attrs)e.setAttribute(k,attrs[k]);
      return e;
    }
    function elG(attrs){return el('g',attrs);}
    function elText(str,x,y,attrs){
      var t=el('text',Object.assign({x:x,y:y,'font-family':'-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif'},attrs));
      t.textContent=str;
      return t;
    }

    /* initial draw + resize */
    draw();
    var resizeTimer;
    window.addEventListener('resize',function(){
      clearTimeout(resizeTimer);
      resizeTimer=setTimeout(draw,100);
    });

    return {getState:function(){return state;},redraw:draw};
  }
};
})();
