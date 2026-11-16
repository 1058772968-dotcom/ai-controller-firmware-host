"""Explicit candidate stackups; fabricator must approve controlled impedance."""
from sexpr import parse,children,one
def install_stackup(tree,copper_layers,dielectrics):
    assert len(dielectrics)==len(copper_layers)-1
    parts=['(stackup (layer "F.SilkS" (type "Top Silk Screen")) (layer "F.Paste" (type "Top Solder Paste")) (layer "F.Mask" (type "Top Solder Mask") (thickness 0.01) (epsilon_r 3.3) (loss_tangent 0))']
    for i,name in enumerate(copper_layers):
        cu=.035 if i in (0,len(copper_layers)-1) else .018
        parts.append(f'(layer "{name}" (type "copper") (thickness {cu}))')
        if i<len(dielectrics):parts.append(f'(layer "dielectric {i+1}" (type "{("core" if i==len(dielectrics)//2 else "prepreg")}") (thickness {dielectrics[i]}) (material "FR4 controlled impedance target") (epsilon_r 4.3) (loss_tangent 0.02))')
    parts.append('(layer "B.Mask" (type "Bottom Solder Mask") (thickness 0.01) (epsilon_r 3.3) (loss_tangent 0)) (layer "B.Paste" (type "Bottom Solder Paste")) (layer "B.SilkS" (type "Bottom Silk Screen")) (copper_finish "ENIG") (dielectric_constraints yes))')
    setup=one(tree,'setup')
    for old in children(setup,'stackup'):setup.remove(old)
    setup.insert(1,parse(' '.join(parts)))
