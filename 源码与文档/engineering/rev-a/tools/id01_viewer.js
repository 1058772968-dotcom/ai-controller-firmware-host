import * as THREE from '../../../prototype/node_modules/three/build/three.module.js';
import {OrbitControls} from '../../../prototype/node_modules/three/examples/jsm/controls/OrbitControls.js';
import {RoomEnvironment} from '../../../prototype/node_modules/three/examples/jsm/environments/RoomEnvironment.js';

const canvas=document.querySelector('canvas'),stage=document.getElementById('stage');
const renderer=new THREE.WebGLRenderer({canvas,antialias:true,preserveDrawingBuffer:true});
renderer.setPixelRatio(Math.min(devicePixelRatio,2));renderer.shadowMap.enabled=true;
renderer.shadowMap.type=THREE.PCFSoftShadowMap;renderer.outputColorSpace=THREE.SRGBColorSpace;
renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=.92;
const scene=new THREE.Scene();scene.background=new THREE.Color('#f0efeb');
const pmrem=new THREE.PMREMGenerator(renderer);scene.environment=pmrem.fromScene(new RoomEnvironment(),.03).texture;scene.environmentIntensity=.40;
const camera=new THREE.OrthographicCamera(-70,70,80,-80,.1,1500);
const controls=new OrbitControls(camera,canvas);controls.enableDamping=true;controls.target.set(0,56,0);
const root=new THREE.Group();scene.add(root);
const palettes={shell:'#bcbab2',cap:'#d3d0c7',rubber:'#363a38',key:'#393d3c',strap:'#656b65',gap:'#1d2220',metal:'#626865',gold:'#dca443',ink:'#e4e8e3',led:'#51d3ee'};
function texture(woven=false){
  const n=128,data=new Uint8Array(n*n*4);let seed=7151;
  for(let y=0;y<n;y++)for(let x=0;x<n;x++){seed=(Math.imul(seed,1664525)+1013904223)>>>0;const v=100+(seed%70)+(woven?((Math.floor((x+y)/3)+Math.floor((x-y+n)/3))%2)*50:0);data.set([v,v,v,255],(y*n+x)*4);}
  const t=new THREE.DataTexture(data,n,n,THREE.RGBAFormat);t.wrapS=t.wrapT=THREE.RepeatWrapping;t.magFilter=THREE.LinearFilter;t.minFilter=THREE.LinearFilter;t.needsUpdate=true;t.repeat.set(woven?1:5,woven?1:10);return t;
}
for(const item of window.NATIVE_MESHES){
  const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(item.vertices.flat(),3));geometry.setIndex(item.faces.flat());if(item.normals)geometry.setAttribute('normal',new THREE.Float32BufferAttribute(item.normals.flat(),3));else geometry.computeVertexNormals();
  const uv=item.vertices.flatMap(v=>item.role==='strap'?[(v[0]*-.45+v[2]*.893)/12,v[1]/12]:[Math.atan2(v[2]+3,v[0])/(2*Math.PI)+.5,v[1]/116]);geometry.setAttribute('uv',new THREE.Float32BufferAttribute(uv,2));
  const role=item.role,soft=['rubber','strap'].includes(role),bump=soft?texture(role==='strap'):null;
  const material=new THREE.MeshPhysicalMaterial({color:palettes[role],roughness:soft?.97:role==='metal'?.5:role==='key'?.65:.78,metalness:['gold','metal'].includes(role)?.25:0,clearcoat:0,map:role==='strap'?bump:null,bumpMap:bump,bumpScale:role==='strap'?.18:.055});
  if(role==='led'){material.emissive.set('#20bbde');material.emissiveIntensity=.35;}
  const mesh=new THREE.Mesh(geometry,material);mesh.name=item.name;mesh.castShadow=true;mesh.receiveShadow=true;root.add(mesh);
}
scene.add(new THREE.HemisphereLight('#ffffff','#b8b4aa',.65));
const key=new THREE.DirectionalLight('#fff7e9',1.8);key.position.set(-90,420,130);key.castShadow=true;key.shadow.mapSize.set(2048,2048);Object.assign(key.shadow.camera,{left:-100,right:100,top:150,bottom:-100,near:1,far:800});key.shadow.bias=-.0004;key.shadow.normalBias=.15;scene.add(key);
const fill=new THREE.DirectionalLight('#ecf3ff',.65);fill.position.set(110,100,-140);scene.add(fill);
const floor=new THREE.Mesh(new THREE.PlaneGeometry(1000,1000),new THREE.ShadowMaterial({opacity:.055}));floor.rotation.x=-Math.PI/2;floor.position.y=-.3;floor.receiveShadow=true;scene.add(floor);
const views={hero:[-150,130,210],front:[0,86,240],rear:[0,86,-240],left:[-240,78,0],right:[240,78,0],top:[0,280,75],bottom:[0,-260,-35]};
const names={hero:'外观',front:'正视',rear:'后视',left:'左视',right:'右视',top:'俯视',bottom:'仰视'};
let current='hero';
function resize(){const w=stage.clientWidth,h=stage.clientHeight;renderer.setSize(w,h,false);const aspect=w/h;camera.left=-78*aspect;camera.right=78*aspect;camera.top=78;camera.bottom=-78;camera.updateProjectionMatrix();}
function view(name){current=name;camera.up.set(0,1,0);if(name==='top')camera.up.set(0,0,-1);if(name==='bottom')camera.up.set(0,0,1);camera.position.set(...views[name]);controls.target.set(0,55,0);controls.update();floor.visible=name!=='bottom';document.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===name));document.getElementById('view-name').textContent=names[name];renderer.render(scene,camera);}
for(const [name,label]of Object.entries(names)){const b=document.createElement('button');b.dataset.view=name;b.textContent=label;b.onclick=()=>view(name);document.querySelector('nav').append(b);}
document.getElementById('reference-toggle').onchange=e=>{document.querySelector('.reference').hidden=!e.target.checked;resize();};
window.addEventListener('resize',resize);resize();view('hero');
window.ID01={view,ready:true,partCount:root.children.length,render:()=>renderer.render(scene,camera),silhouette(){const previous=root.children.map(m=>m.material),bg=scene.background,ground=floor.visible;const black=new THREE.MeshBasicMaterial({color:0});root.children.forEach(m=>m.material=black);scene.background=new THREE.Color('white');floor.visible=false;renderer.render(scene,camera);const png=canvas.toDataURL('image/png');root.children.forEach((m,i)=>m.material=previous[i]);scene.background=bg;floor.visible=ground;black.dispose();renderer.render(scene,camera);return png;},setOrtho(name){view(name);const c={front:[0,55,240],rear:[0,55,-240],left:[-240,55,0],right:[240,55,0],top:[0,280,0],bottom:[0,-260,0]};camera.position.set(...c[name]);controls.update();renderer.render(scene,camera);}};
function frame(){requestAnimationFrame(frame);controls.update();renderer.render(scene,camera);}frame();
