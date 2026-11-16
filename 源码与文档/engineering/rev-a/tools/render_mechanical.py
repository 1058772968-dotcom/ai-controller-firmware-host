from pathlib import Path
import sys,argparse
sys.path.insert(0,'/Applications/FreeCAD.app/Contents/Resources/lib')
import FreeCAD as App
import FreeCADGui as Gui
Gui.showMainWindow()
r=Path(__file__).resolve().parents[1]
ap=argparse.ArgumentParser();ap.add_argument('--revision');args=ap.parse_args()
name='AIKEY_REVA'+('_DESIGN'+args.revision if args.revision else '')
d=App.openDocument(str(r/'mechanical'/f'{name}.FCStd'))
for o in d.Objects:
    if o.ViewObject:o.ViewObject.Visibility=False
colors={'FingerShell':(.74,.73,.69),'FingerShellSupported':(.74,.73,.69),'PalmShell':(.66,.66,.63),'TopCover':(.82,.81,.77),'TopCoverSupported':(.82,.81,.77),'AntennaFPC':(.5,.3,.13)}
for o in d.Assembly.Group:
    o.ViewObject.Visibility=True;o.ViewObject.DisplayMode='Flat Lines'
    o.ViewObject.ShapeColor=colors.get(o.Name,(.2,.3,.35) if 'Key' in o.Name else (.12,.5,.4))
d.Assembly.ViewObject.Visibility=True
v=Gui.activeDocument().activeView()
v.setCameraOrientation(App.Rotation(App.Vector(0,0,1),App.Vector(1,.55,1.8)).Q)
v.fitAll()
Gui.updateGui()
# First native OpenGL frame can be blank on macOS. Render one discarded warmup
# frame, then capture both deliverable views after explicit redraws.
v.redraw();Gui.updateGui()
v.saveImage(str(r/'reports'/f'mechanical-{name}-warmup.png'),1400,1100,'White')
for o in d.Assembly.Group:
    if o.Name in ('PalmShell','FingerShell','FingerShellSupported','TopCover','TopCoverSupported'):
        o.ViewObject.Transparency=85
Gui.updateGui();v.redraw();Gui.updateGui()
v.saveImage(str(r/'reports'/f'mechanical-{name}-internal.png'),1400,1100,'White')
for o in d.Assembly.Group:
    if o.Name in ('PalmShell','FingerShell','FingerShellSupported','TopCover','TopCoverSupported'):
        o.ViewObject.Transparency=0
Gui.updateGui();v.redraw();Gui.updateGui()
v.saveImage(str(r/'reports'/f'mechanical-{name}-assembled.png'),1400,1100,'White')
print('render saved',flush=True)
App.closeDocument(d.Name)
Gui.getMainWindow().close()
