"""Image-space silhouette overlays; never substitutes for native dimensions."""
from pathlib import Path
import json,os
import numpy as np
from PIL import Image,ImageFilter,ImageDraw,ImageFont,ImageChops
R=Path(__file__).resolve().parents[1];D=Path(os.environ.get('ID01_OUTPUT_DIR',str(R/'mechanical/id01-reference')))
source=Image.open(D/'user-reference.png').convert('RGB')
ROIS={'front':(200,98,382,488),'rear':(659,102,866,488),'left':(1166,114,1406,489),
      'right':(157,533,378,933),'top':(662,599,890,897),'bottom':(1158,598,1380,897)}
def clean(mask):
    mask=mask.filter(ImageFilter.MinFilter(5)).filter(ImageFilter.MaxFilter(5))
    a=np.array(mask)>128;seen=np.zeros_like(a);best=[]
    for y,x in zip(*np.where(a)):
        if seen[y,x]:continue
        pending=[(y,x)];seen[y,x]=True;component=[]
        while pending:
            yy,xx=pending.pop();component.append((yy,xx))
            for dy,dx in ((1,0),(-1,0),(0,1),(0,-1)):
                ny,nx=yy+dy,xx+dx
                if 0<=ny<a.shape[0] and 0<=nx<a.shape[1] and a[ny,nx] and not seen[ny,nx]:seen[ny,nx]=True;pending.append((ny,nx))
        if len(component)>len(best):best=component
    result=np.zeros_like(a,dtype=np.uint8)
    for y,x in best:result[y,x]=255
    # Image.fromarray can expose a read-only buffer. floodfill uses PixelAccess
    # and must receive a writable copy, otherwise no background is marked.
    result=Image.fromarray(result).copy();ImageDraw.floodfill(result,(0,0),128)
    if result.getpixel((0,0))!=128:raise RuntimeError('Reference mask background flood failed')
    arr=np.array(result);arr[arr==0]=255;arr[arr==128]=0
    return Image.fromarray(arr)
def font(size):
    for p in ['/System/Library/Fonts/PingFang.ttc','/System/Library/Fonts/Supplemental/Arial.ttf']:
        try:return ImageFont.truetype(p,size)
        except OSError:pass
    return ImageFont.load_default()
sheet=Image.new('RGB',(1500,1160),'#f8f8f3');draw=ImageDraw.Draw(sheet)
draw.text((35,22),'ID-01 / Reference silhouette comparison',font=font(26),fill='#29302c')
draw.text((35,62),'Gray: shared area  |  Coral: reference only  |  Blue: CAD only',font=font(17),fill='#666e66')
rows=[]
for n,(view,roi) in enumerate(ROIS.items()):
    ref=source.crop(roi);a=np.array(ref);mask=Image.fromarray(np.uint8(a.mean(axis=2)<241)*255);mask=clean(mask)
    native=Image.open(D/(view+'-silhouette.png')).convert('L').point(lambda x:255 if x<128 else 0)
    native=native.crop(native.getbbox());bounds=mask.getbbox();height=bounds[3]-bounds[1]
    scale=height/native.height;native=native.resize((round(native.width*scale),height),Image.Resampling.LANCZOS).point(lambda x:255 if x>128 else 0)
    x0=round((bounds[0]+bounds[2]-native.width)/2);y0=bounds[1];ra=np.array(mask)>128;best=(-1,None,None,None)
    for dy in range(-5,6):
        for dx in range(-12,13):
            fit=Image.new('L',mask.size);fit.paste(native,(x0+dx,y0+dy));ma=np.array(fit)>128
            union=np.logical_or(ra,ma).sum();iou=np.logical_and(ra,ma).sum()/max(1,union)
            if iou>best[0]:best=(iou,fit,dx,dy)
    iou,fit,dx,dy=best;ma=np.array(fit)>128;out=np.full((*ra.shape,3),248,dtype=np.uint8)
    out[ra&ma]=[205,210,204];out[ra&~ma]=[222,124,99];out[ma&~ra]=[95,158,196]
    overlay=Image.fromarray(out);overlay.save(D/(view+'-overlay.png'))
    col,row=n%3,n//3;x,y=30+col*490,110+row*490
    draw.text((x,y),view.upper(),font=font(20),fill='#29302c')
    draw.text((x+225,y),'IoU %.3f'%iou,font=font(16),fill='#6b736a')
    thumb=ref.copy();thumb.thumbnail((200,405));sheet.paste(thumb,(x,y+45))
    overlay.thumbnail((235,405));sheet.paste(overlay,(x+225,y+45))
    rows.append({'view':view,'reference_roi_pixels':roi,'uniform_scale_to_reference_height':scale,'translation_search_pixels':[dx,dy],'image_space_iou':iou})
draw.text((35,1100),'Uniform scale + translation only. Concept-view perspective and annotations limit this comparison.',font=font(16),fill='#6b736a')
draw.text((35,1128),'No independent width/depth stretching. This is not an acceptance of unseen geometry or internal fit.',font=font(16),fill='#6b736a')
sheet.save(D/'six-view-silhouette-comparison.png')
(D/'silhouette-comparison.json').write_text(json.dumps({'status':'IMAGE_SPACE_COMPARISON_ONLY','method':'Largest object mask after 5px annotation-line removal and hole fill; CAD silhouette scaled uniformly to reference object height, translated only; no aspect warping. Different reference view perspective prevents a literal simultaneous 1:1 pixel match.','views':rows},indent=2)+'\n')
print(json.dumps(rows),flush=True)
