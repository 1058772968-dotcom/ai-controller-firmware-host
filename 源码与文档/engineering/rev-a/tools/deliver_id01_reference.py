"""Publish a validated local CAD review snapshot into the project directory."""
from pathlib import Path
import hashlib, json, shutil, datetime, zipfile, os, tempfile

R = Path(__file__).resolve().parents[1]
S = Path.home() / '.cache/ai-key-rev-a/id01-reference'
D = R / 'mechanical/id01-reference'
NAME = 'AIKEY_ID01_REFERENCE_04'
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

native = json.loads((S/'native-readback.json').read_text())
mesh = json.loads((S/'mesh-export-validation.json').read_text())
viewer = json.loads((S/'viewer-validation.json').read_text())
assert native['status'] == 'PASS' and all(native['checks'].values())
assert native['sha256'] == mesh['source_sha256'] == sha(S/(NAME+'.FCStd'))
assert native['step_sha256'] == sha(S/(NAME+'.step'))
assert viewer['status'] == 'RENDERED_NATIVE_GEOMETRY_AND_RESPONSIVE_VIEW_PASS'
assert viewer['parts'] == native['native_part_count'] == 32
assert viewer['html_sha256'] == sha(S/'ID01-原型对照.html')
assert viewer['mesh_sha256'] == sha(S/'native-meshes.json')
dimensions = native['dimensions']
width, height, depth = dimensions['including_strap_xyz_mm']
notes = f'''# ID-01 原型外形还原 · REV 04

本版按用户提供的六视图重建 FreeCAD 原生外观。用户已明确选择“优先按原图视觉比例还原，实际尺寸另列”。旧 C 外形及其工程文件保留；ESP32-S3 电路和固件功能基线继续沿用。

## 打开文件

- `{NAME}.FCStd`：FreeCAD 原生实体、构造截面、Loft 与外观部件。
- `{NAME}.step`：已回读验证的 STEP 交换文件。
- `ID01-原型对照.html`：离线旋转模型、六个视角与原图对照。显示从同一原生文件导出的几何；材质纹理为示意。
- `ID01-六视图.png`：本版六视图；`six-view-silhouette-comparison.png`：轮廓叠图。
- `native-readback.json`、`viewer-validation.json`、`delivery-manifest.json`：校验及文件指纹。

## 实测尺寸

| 项目 | 当前 CAD / mm | 说明 |
|---|---:|---|
| 高度 | {height:.2f} | 包含拇指键 |
| 顶盖宽 | {dimensions['cap_width_x_mm']:.2f} | X 方向 |
| 顶盖深 | {dimensions['cap_depth_z_mm']:.2f} | 采用视觉比例；原图标注 46，用户确认优先外形 |
| 整机宽 | {width:.2f} | 包含掌带与固定头 |
| 整机前后深 | {depth:.2f} | 包含后弯掌托，不能当作顶盖深度 |

## 本次修改与检查

已重建倾斜蛋形顶盖、近端 L/远端 R、前缘蓝色灯窗、内凹悬垂扳机、左侧金边绘图键、后弯掌托、深色握胶、右侧织物掌带及圆形固定头、底部 USB-C 与挂绳孔。握胶轮廓、掌带弧度、R 字标、曲面预览法线和后部中缝均已复核。

32 个可见原生部件均为有效实体，主壳为单一实体；保存后重开通过，STEP 回读实体数一致。离线页面经过实际浏览器渲染，390 px 宽度无横向溢出。轮廓叠图采用等比缩放和位移，没有分别拉伸宽高；分割受阴影、标注和视角影响，该指标不等于外观或装配验收。

## 仍需完成

这是外观重建版，尚非完整内部装配或制造发布。新壳的 PCB、电池、天线、USB、麦克风、开关机构、螺钉与线束须重新定位并验算，旧版装配通过记录不直接沿用。没有样机，也没有宣称实物验收。

原图各视角存在透视和标注冲突：除深度标注外，俯视图灯窗所在端与正/侧视图不一致。本版灯窗保持正/侧视图的前缘位置。因此目前不标注“逐视图 1:1 终验通过”。

结构截面和生成参数在 `../../tools/build_id01_reference.py`。参数修改后需重建；最终布尔实体不是全部由电子表格实时驱动的装配。原生重开、网格导出和预览脚本也位于该 tools 目录。
'''
(S/'README.md').write_text(notes)
files = [NAME+'.FCStd', NAME+'.step', 'README.md', 'ID01-原型对照.html', 'ID01-六视图.png',
         'user-reference.png', 'FreeCAD-native.png', 'native-readback.json', 'native-validation.json',
         'native-meshes.json', 'mesh-export-validation.json', 'viewer-validation.json',
         'silhouette-comparison.json', 'six-view-silhouette-comparison.png', 'reference-comparison.png',
         'mobile-preview.png', 'viewer.bundle.js']
files += [v+'.png' for v in ['hero','front','rear','left','right','top','bottom']]
manifest = {'status':'VALIDATED_NATIVE_EXTERIOR_REVIEW_DELIVERY', 'revision':NAME,
    'created_at':datetime.datetime.now().astimezone().isoformat(),
    'scope':'Exterior review only; full assembly and literal six-view image-exact acceptance remain open.',
    'native_sha256':native['sha256'], 'files':[]}
for name in files:
    target=D/name
    # Opening an offloaded iCloud target with 'wb' can block on hydration.
    # Copy to a fresh file, verify it, then replace our generated target.
    fd, temporary = tempfile.mkstemp(prefix='.rev04-', dir=D)
    os.close(fd)
    temporary=Path(temporary)
    shutil.copy2(S/name, temporary)
    expected=sha(S/name)
    assert sha(temporary)==expected, name
    os.replace(temporary,target)
    assert sha(target)==expected, name
    manifest['files'].append({'path':name, 'bytes':target.stat().st_size, 'sha256':expected})
sources = ['build_id01_reference.py','build_mechanical.py','finalize_id01_native.py',
           'export_id01_meshes.py','id01_viewer.js','package_id01_viewer.py',
           'render_id01_review.cjs','compare_id01_silhouettes.py','create_id01_sheet.py',
           'deliver_id01_reference.py']
manifest['source_files']=[{'path':'../../tools/'+n,'sha256':sha(R/'tools'/n)} for n in sources]
(D/'delivery-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
archive=D/'ID01-原型还原-REV04.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
    for name in [NAME+'.FCStd',NAME+'.step','README.md','ID01-原型对照.html','ID01-六视图.png',
                 'user-reference.png','native-readback.json','silhouette-comparison.json','delivery-manifest.json']:
        z.write(D/name, name)
    for name in sources:
        z.write(R/'tools'/name, 'source/'+name)
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
(D/'delivery-archive.json').write_text(json.dumps({'archive':archive.name,'sha256':sha(archive),'bytes':archive.stat().st_size,'zip_readback':'PASS'},indent=2)+'\n')
print(json.dumps({'delivered_files':len(files),'native':str(D/(NAME+'.FCStd')),'archive':str(archive),'native_sha256':native['sha256']},ensure_ascii=False),flush=True)
