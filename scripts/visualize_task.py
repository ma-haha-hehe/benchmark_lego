#!/usr/bin/env python3
"""Render paper-style or exact STL/YAML previews; no simulation or task mutation.

Optional dependencies: numpy, matplotlib, Pillow and PyYAML.
Drawing helpers for render_gallery.py; the CLI delegates to the canonical
per-tier gallery renderer.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile
import zipfile

os.environ.setdefault('MPLCONFIGDIR', str(Path(tempfile.gettempdir()) / 'benchmark-lego-mpl'))
os.environ.setdefault('XDG_CACHE_HOME', str(Path(tempfile.gettempdir()) / 'benchmark-lego-cache'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import to_rgb
from matplotlib.patches import Circle, Rectangle
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import yaml

COLORS = {'red': '#d94c4c', 'blue': '#4287d8', 'yellow': '#ebba32', 'green': '#40a86e'}
PAPER_COLORS = {'red': '#ff0000', 'blue': '#0000ff', 'yellow': '#ffff00', 'green': '#008000'}
CLASSES = ('two_brick_stack', 'simple_multi_brick_stack',
           'simple_shape_assembly', 'balanced_order_sensitive')
LABELS = ('Two-brick stack', 'Multi-brick stack', 'Supported shape', 'External overhang')
W, H = 960, 800
BG = '#f6f8fb'
STYLE = 'paper'
CENTRE_AUDIT = []
AXIS_AUDIT = []
GUIDE_CONTEXT = {}
ANNOTATION_VERSION = 'ground-envelope-axis-v1'
MAGENTA, PURPLE, TEAL, ORANGE = '#c026b5', '#8b3fc0', '#087e8b', '#f97316'
TIER_CAPTIONS = {1:'TIER 1: 2 same-type bricks; same XY centre; fixed yaw.',
                 2:'TIER 2: 2-5 same-type bricks (mostly 2-3); same XY centre; yaw 0 / 90 degrees.',
                 3:'TIER 3: 3-12 bricks; bridges; full upper footprints inside ground envelope.',
                 4:'TIER 4: 3-12 bricks; at least one upper CENTRE on / outside ground envelope.'}


def tier_caption():
    return TIER_CAPTIONS.get(GUIDE_CONTEXT.get('tier'),'')


def ground_reference(blocks):
    """Geometric reference from the nominal ground envelope, never centre of mass."""
    _, _, _, g = summary(blocks)
    return np.array([(g[0]+g[1])/2, (g[2]+g[3])/2]), g


def audit_guides(view, blocks, reference, ground, centres=None, **details):
    AXIS_AUDIT.append({**GUIDE_CONTEXT, 'view': view,
        'annotation_version': ANNOTATION_VERSION,
        'reference_role': 'ground_envelope_midpoint' if ground is not None else 'initial_parts_plate_midpoint',
        'reference_world_xy_mm': np.asarray(reference).tolist(),
        'ground_envelope_world_mm': None if ground is None else np.asarray(ground).tolist(),
        'brick_world_xy_mm': (np.array([b['pos'][:2] for b in blocks])*1000).tolist() if centres is None else np.asarray(centres).tolist(),
        **details})


def overlay_line(draw, start, end, color, dashed=False, width=3):
    start, end = np.asarray(start), np.asarray(end)
    length = np.linalg.norm(end-start)
    for distance in np.arange(0, max(length, 1), 14 if dashed else max(length, 1)):
        p = start+(end-start)*(distance/max(length, 1))
        q = start+(end-start)*(min(distance+(8 if dashed else length), length)/max(length, 1))
        draw.line([tuple(p), tuple(q)], fill='white', width=width+2)
        draw.line([tuple(p), tuple(q)], fill=color, width=width)


def overlay_label(draw, xy, text, color):
    draw.text(tuple(xy), text, font=font(16), fill=color, stroke_width=2, stroke_fill='white')


def load_yaml(path):
    with path.open(encoding='utf-8') as stream:
        return yaml.safe_load(stream)


def load_mesh(path, brick_type):
    raw = path.read_bytes()
    if len(raw) < 84:
        raise ValueError(f'Truncated STL: {path}')
    count = int.from_bytes(raw[80:84], 'little')
    dtype = np.dtype([('normal', '<f4', (3,)), ('vertices', '<f4', (3, 3)), ('attribute', '<u2')])
    if len(raw) != 84 + count * dtype.itemsize:
        raise ValueError(f'Expected binary STL: {path}')
    triangles = np.frombuffer(raw, dtype=dtype, count=count, offset=84)['vertices'].astype(float)
    triangles[:, :, :2] -= np.array([32, 16] if brick_type == 'brick_4x2' else [16, 16])
    return triangles


def paper_mesh(brick_type):
    """Fig. 1/3-style schematic: nominal solid body and solid round studs.

    This is a visual proxy, not a modification of the actual STL asset. Body
    height is the YAML's 20 mm engaged layer pitch; stud height is 3.75 mm.
    """
    width = 64. if brick_type == 'brick_4x2' else 32.
    depth, height = 32., 20.
    vertices = np.array([[-width/2, -depth/2, 0], [width/2, -depth/2, 0],
                         [width/2, depth/2, 0], [-width/2, depth/2, 0],
                         [-width/2, -depth/2, height], [width/2, -depth/2, height],
                         [width/2, depth/2, height], [-width/2, depth/2, height]])
    quads = ((0,3,2,1), (4,5,6,7), (0,1,5,4), (1,2,6,5), (2,3,7,6), (3,0,4,7))
    triangles, edges = [], []
    for a,b,c,d in quads:
        triangles.extend((vertices[[a,b,c]], vertices[[a,c,d]]))
    for a,b in ((0,1),(1,2),(2,3),(3,0),(4,5),(5,6),(6,7),(7,4),(0,4),(1,5),(2,6),(3,7)):
        edges.append(vertices[[a,b]])
    angle = np.linspace(0, 2*np.pi, 33)[:-1]
    for x in np.arange(-width/2+8, width/2, 16):
        for y in (-8., 8.):
            ring = np.column_stack((x+4.6*np.cos(angle), y+4.6*np.sin(angle), np.full(32,height)))
            top = ring.copy(); top[:, 2] += 3.75
            top_center = np.array([x,y,height+3.75])
            for i in range(32):
                j = (i+1)%32
                triangles.extend((np.array([ring[i],ring[j],top[j]]),
                                  np.array([ring[i],top[j],top[i]]),
                                  np.array([top_center,top[i],top[j]])))
                edges.extend((np.array([top[i],top[j]]), np.array([ring[i],ring[j]]), np.array([ring[i],top[i]])))
    return np.array(triangles), np.array(edges)


def dims(block):
    size = np.array([64., 32.] if block['type'] == 'brick_4x2' else [32., 32.])
    if round(math.degrees(block['rotation'][2])) % 180 == 90:
        size = size[::-1]
    return size


def box(block):
    p = np.array(block['pos'][:2]) * 1000
    d = dims(block) / 2
    return np.array([p[0]-d[0], p[0]+d[0], p[1]-d[1], p[1]+d[1]])


def level(block):
    return int(round(block['pos'][2] / .020))


def overlap(a, b):
    return max(0., min(a[1], b[1])-max(a[0], b[0])) * max(0., min(a[3], b[3])-max(a[2], b[2]))


def summary(blocks):
    support = [sum(overlap(box(b), box(o)) for o in blocks if level(o) == level(b)-1)
               / np.prod(dims(b)) for b in blocks if level(b) > 0]
    ground = [box(b) for b in blocks if level(b) == 0]
    g = np.array([min(b[0] for b in ground), max(b[1] for b in ground),
                  min(b[2] for b in ground), max(b[3] for b in ground)])
    external = any((box(b)[0] < g[0]-1e-5 or box(b)[1] > g[1]+1e-5 or
                    box(b)[2] < g[2]-1e-5 or box(b)[3] > g[3]+1e-5)
                   for b in blocks if level(b) > 0)
    return max(level(b) for b in blocks)+1, min(support, default=1.), external, g


def draw_mesh(blocks, meshes, title, azimuth, center_guides=False, elevation=None,
              reference_xy=None, brick_ids=None, boundary_centres=False):
    all_boxes = np.array([box(b) for b in blocks])
    center = np.array([(all_boxes[:, 0].min()+all_boxes[:, 1].max())/2,
                       (all_boxes[:, 2].min()+all_boxes[:, 3].max())/2, 0.])
    reference, ground = ground_reference(blocks) if reference_xy is None else (np.asarray(reference_xy)*1000, None)
    brick_ids = brick_ids or {b['name']: i for i,b in enumerate(blocks,1)}
    faces, colors, normals, outline, body_centres = [], [], [], [], []
    light = np.array([-.4, -.6, .8]); light /= np.linalg.norm(light)
    for b in blocks:
        yaw = b['rotation'][2]
        rot = np.array([[math.cos(yaw), -math.sin(yaw), 0.],
                        [math.sin(yaw), math.cos(yaw), 0.], [0., 0., 1.]])
        geometry = meshes[b['type']][0] if STYLE == 'paper' else meshes[b['type']]
        tri = geometry @ rot.T + np.array(b['pos']) * 1000 - center
        # Audit the actual transformed vertices used below, not just YAML.
        mesh_xy = (tri[:, :, :2].min(axis=(0,1))+tri[:, :, :2].max(axis=(0,1)))/2
        expected_xy = np.array(b['pos'][:2])*1000-center[:2]
        if np.max(np.abs(mesh_xy-expected_xy)) > 1e-6:
            raise ValueError(f'Rendered mesh centre shifted: {b["name"]}')
        body_centres.append([*mesh_xy,b['pos'][2]*1000+10])
        if STYLE == 'paper':
            outline.append(meshes[b['type']][1] @ rot.T + np.array(b['pos'])*1000-center)
        normal = np.cross(tri[:, 1]-tri[:, 0], tri[:, 2]-tri[:, 0])
        norms = np.linalg.norm(normal, axis=1)
        normal = normal / np.maximum(norms[:, None], 1e-12)
        shade = np.ones(len(normal)) if STYLE == 'paper' else .60 + .40 * np.clip(normal @ light, 0., 1.)
        faces.append(tri)
        colors.append(np.clip(np.array(to_rgb(COLORS[b['color']]))[None, :] * shade[:, None], 0, 1))
        normals.append(normal)
    faces = np.concatenate(faces); colors = np.concatenate(colors); normals = np.concatenate(normals)
    fig = plt.figure(figsize=(8, 6.6667), dpi=120, facecolor=BG)
    ax = fig.add_subplot(111, projection='3d', computed_zorder=False)
    ax.set_facecolor(BG)
    ax.set_proj_type('ortho')
    lo = faces.reshape(-1, 3).min(axis=0)
    hi = faces.reshape(-1, 3).max(axis=0)
    width = max(hi[0]-lo[0], hi[1]-lo[1], 64.)
    lim = max(width/2+14, float(np.max(np.abs(reference-center[:2])))+40)
    ax.set_xlim(-lim, lim); ax.set_ylim(-lim, lim)
    ztop = max(hi[2]+20, 64) if STYLE == 'paper' else max(hi[2]+6, 48)
    ax.set_zlim(0, ztop)
    ax.set_box_aspect([2*lim, 2*lim, ztop], zoom=.95)
    elev = elevation if elevation is not None else (25 if STYLE == 'paper' else 26)
    ax.view_init(elev=elev, azim=azimuth)
    if STYLE == 'paper':
        for setter, labelsetter, bounds in ((ax.set_xticks,ax.set_xticklabels,(-lim,lim)),
                                            (ax.set_yticks,ax.set_yticklabels,(-lim,lim)),
                                            (ax.set_zticks,ax.set_zticklabels,(0,ztop))):
            step = 16 if bounds[1]-bounds[0] <= 160 else 48
            setter(np.arange(math.ceil(bounds[0]/step)*step, bounds[1]+1, step)); labelsetter([])
        fig.text(.5,.045,title,ha='center',va='center',fontsize=12,fontfamily='serif')
    else:
        ax.set_xlabel('X (mm, centered)', labelpad=8)
        ax.set_ylabel('Y (mm, centered)', labelpad=8)
        ax.set_zlabel('Z (mm)', labelpad=5)
        ax.tick_params(labelsize=9, pad=0)
        ax.set_title(title, fontsize=14, fontweight='bold', pad=10)
    for axis in (ax.xaxis, ax.yaxis, ax.zaxis):
        axis.pane.fill = STYLE == 'paper'
        axis.pane.set_facecolor((.94,.94,.94,1))
        axis._axinfo['grid']['color'] = (.65,.65,.65,.55) if STYLE == 'paper' else (.7, .75, .8, .35)
        axis._axinfo['grid']['linewidth'] = .5
    fig.text(.5,.965,f'TOTAL: {len(blocks)} BRICKS  |  Studs are part of each brick',
             ha='center',va='center',fontsize=14,fontweight='bold',color='#172b45')
    if center_guides:
        centres = np.array(body_centres)
        offset = np.max(np.abs(centres[:, :2]-centres[0, :2]))
        if offset > 1e-6:
            raise ValueError('Tier 2 rendered brick centres are not aligned')
        xy = np.array(blocks[0]['pos'][:2])*1000
        fig.text(.5,.925,f'Common world XY = ({xy[0]:g}, {xy[1]:g}) mm | centre offset = {offset:.6f} mm',
                 ha='center',va='center',fontsize=11,color='#172b45')

        CENTRE_AUDIT.append({'title':title,'azimuth':azimuth,'elevation':elev,
                             'rendered_world_xy_centres_mm':(centres[:, :2]+center[:2]).tolist(),
                             'maximum_xy_centre_offset_mm':float(offset)})
    if not center_guides:
        role = 'Ground-envelope reference G' if ground is not None else 'Initial parts-plate reference P'
        fig.text(.5,.925,f'{role} = ({reference[0]:g}, {reference[1]:g}) mm',
                 ha='center', va='center', fontsize=11, color='#172b45')
    fig.text(.5,.10,'Magenta: reference Z-axis | Teal: +X / +Y | C1...CN: brick centres',
             ha='center', fontsize=9, color='#334155')
    fig.text(.5,.073,'Purple: nominal ground boundary | Orange: qualifying upper centre' if ground is not None else
             'Initial parts may be separated; their centres need not share an axis.',
             ha='center', fontsize=9, color='#334155')
    if ground is not None:fig.text(.5,.017,tier_caption(),ha='center',fontsize=9,color='#172b45')
    fig.subplots_adjust(left=.03, right=.97, top=.88, bottom=.14)
    # Matplotlib's painter sorting exposes internal faces through the large STL
    # wall triangles. Rasterize opaque meshes with a per-pixel depth buffer instead.
    fig.canvas.draw()
    canvas = np.asarray(fig.canvas.buffer_rgba())[:, :, :3].copy()
    elevation, az = math.radians(elev), math.radians(azimuth)
    toward_camera = np.array([math.cos(elevation)*math.cos(az), math.cos(elevation)*math.sin(az), math.sin(elevation)])
    visible = normals @ toward_camera > 1e-9
    projected = project_triangles(faces[visible], ax, canvas.shape[0])
    zbuffer = rasterize(canvas, projected, colors[visible])
    if STYLE == 'paper':
        lines = np.concatenate(outline)
        projected_lines = project_triangles(lines, ax, canvas.shape[0], points_per_face=2)
        rasterize_edges(canvas, zbuffer, projected_lines)
    overlay = Image.fromarray(canvas)
    draw = ImageDraw.Draw(overlay)
    centres = np.array(body_centres)
    reference_local = reference-center[:2]
    def project(points):
        return project_triangles(np.asarray(points)[:,None,:],ax,canvas.shape[0],points_per_face=1)[:,0,:2]
    axis_top = max(b['pos'][2]*1000 for b in blocks)+32.
    base, tip = project([[*reference_local,0],[*reference_local,axis_top]])
    overlay_line(draw,base,tip,MAGENTA,dashed=True)
    overlay_label(draw,tip+np.array([8,-14]),'Z / G' if ground is not None else 'Z / P',MAGENTA)
    arm = min(32.,lim*.65)
    for i, label in enumerate(('+X','+Y')):
        endpoint=np.array([*reference_local,0.]);endpoint[i]+=arm
        arrow=project([endpoint])[0]
        overlay_line(draw,base,arrow,TEAL,width=2)
        direction=(arrow-base)/max(np.linalg.norm(arrow-base),1)
        normal=np.array([-direction[1],direction[0]])
        draw.polygon([tuple(arrow),tuple(arrow-8*direction+3*normal),tuple(arrow-8*direction-3*normal)],fill=TEAL)
        overlay_label(draw,arrow+4*direction,label,TEAL)
    if ground is not None:
        g=ground
        corners=np.array([[g[0],g[2],0],[g[1],g[2],0],[g[1],g[3],0],[g[0],g[3],0],[g[0],g[2],0]])-center
        pixels=project(corners)
        for a,b in zip(pixels,pixels[1:]):overlay_line(draw,a,b,PURPLE,dashed=True,width=2)
    projected_points = project(centres)
    qualifying_ids=[]
    for b,(x,y) in zip(blocks,projected_points):
        j=brick_ids[b['name']]
        xy=np.array(b['pos'][:2])*1000
        margin=None if ground is None else max(ground[0]-xy[0],xy[0]-ground[1],ground[2]-xy[1],xy[1]-ground[3])
        qualifying=boundary_centres and ground is not None and level(b)>0 and margin>=-1e-5
        color=ORANGE if qualifying else (MAGENTA if center_guides else '#243346')
        if qualifying:
            qualifying_ids.append(j)
            lower=project([[*(xy-center[:2]),0]])[0]
            overlay_line(draw,lower,(x,y),ORANGE,dashed=True,width=2)
        draw.ellipse((x-6,y-6,x+6,y+6),fill=color,outline='white',width=2)
        overlay_label(draw,(x+10,y-9),f'C{j}',color)
    audit_guides('mesh',blocks,reference,ground,centres[:,:2]+center[:2],
                 azimuth=azimuth,elevation=elev,qualifying_ids=qualifying_ids,
                 projected_axis_pixels=[base.tolist(),tip.tolist()],projected_centres_pixels=projected_points.tolist())
    canvas = np.asarray(overlay)
    plt.close(fig)
    return Image.fromarray(canvas).resize((W, H))


def project_triangles(faces, ax, image_height, points_per_face=3):
    points = faces.reshape(-1, 3)
    clip = np.column_stack((points, np.ones(len(points)))) @ ax.get_proj().T
    ndc = clip[:, :3] / clip[:, 3, None]
    pixels = ax.transData.transform(ndc[:, :2])
    pixels[:, 1] = image_height - pixels[:, 1]
    return np.column_stack((pixels, ndc[:, 2])).reshape(-1, points_per_face, 3)


def rasterize(canvas, triangles, colors):
    """Orthographic opaque triangle rasterizer; nearest projected Z wins."""
    height, width = canvas.shape[:2]
    depth = np.full((height, width), np.inf, dtype=np.float32)
    for triangle, color in zip(triangles, colors):
        x, y, z = triangle.T
        xmin = max(0, math.floor(x.min())); xmax = min(width-1, math.ceil(x.max()))
        ymin = max(0, math.floor(y.min())); ymax = min(height-1, math.ceil(y.max()))
        if xmax < xmin or ymax < ymin:
            continue
        divisor = (y[1]-y[2])*(x[0]-x[2]) + (x[2]-x[1])*(y[0]-y[2])
        if abs(divisor) < 1e-10:
            continue
        px = np.arange(xmin, xmax+1, dtype=float)[None, :] + .5
        py = np.arange(ymin, ymax+1, dtype=float)[:, None] + .5
        a = ((y[1]-y[2])*(px-x[2]) + (x[2]-x[1])*(py-y[2]))/divisor
        b = ((y[2]-y[0])*(px-x[2]) + (x[0]-x[2])*(py-y[2]))/divisor
        c = 1-a-b
        interpolated = a*z[0] + b*z[1] + c*z[2]
        current = depth[ymin:ymax+1, xmin:xmax+1]
        mask = (a >= -1e-7) & (b >= -1e-7) & (c >= -1e-7) & (interpolated < current)
        current[mask] = interpolated[mask]
        canvas[ymin:ymax+1, xmin:xmax+1][mask] = np.round(color*255).astype(np.uint8)
    return depth


def rasterize_edges(canvas, depth, lines):
    """Thin black body/stud contours, clipped against opaque mesh depth."""
    height,width = depth.shape
    for a,b in lines:
        steps = max(2,math.ceil(np.max(np.abs(b[:2]-a[:2]))*2)+1)
        t = np.linspace(0,1,steps)[:,None]
        p = a[None,:]*(1-t)+b[None,:]*t
        x = np.floor(p[:,0]).astype(int); y = np.floor(p[:,1]).astype(int)
        valid = (x>=0)&(x<width)&(y>=0)&(y<height)
        x,y,z = x[valid],y[valid],p[valid,2]
        visible = z <= depth[y,x]+.0008
        x,y = x[visible],y[visible]
        canvas[y,x] = np.round(canvas[y,x].astype(float)*.65).astype(np.uint8)


def figure_image(fig):
    stream = io.BytesIO()
    fig.savefig(stream, dpi=120, facecolor=BG)
    plt.close(fig)
    stream.seek(0)
    return Image.open(stream).convert('RGB').resize((W, H))


def draw_block_2d(ax, b, ident, origin=(0, 0), ghost=False):
    bb = box(b)
    x, y = bb[0]-origin[0], bb[2]-origin[1]
    width, height = dims(b)
    ax.add_patch(Rectangle((x, y), width, height, linewidth=1.1,
                          edgecolor='#667588' if ghost else '#263343',
                          facecolor='none' if ghost else COLORS[b['color']],
                          linestyle='--' if ghost else '-', alpha=.8 if ghost else .94))
    if not ghost:
        for dx in np.arange(8, width, 16):
            for dy in np.arange(8, height, 16):
                ax.add_patch(Circle((x+dx, y+dy), 4.5, facecolor='white', edgecolor='#263343',
                                    alpha=.26, linewidth=.5))



def draw_layers(blocks, center_guides=False, boundary_centres=False):
    n, _, _, g = summary(blocks)
    origin, _ = ground_reference(blocks)
    boxes = np.array([box(b) for b in blocks])
    xmin, xmax = boxes[:,0].min()-origin[0]-12, boxes[:,1].max()-origin[0]+12
    ymin, ymax = boxes[:,2].min()-origin[1]-12, boxes[:,3].max()-origin[1]+12
    cols = min(3,n); rows = math.ceil(n/cols)
    fig, axes = plt.subplots(rows,cols,figsize=(8,6.6667),dpi=120,facecolor=BG,squeeze=False)
    qualifying_ids=[]
    for i,ax in enumerate(axes.flat):
        if i>=n: ax.axis('off'); continue
        ax.set_facecolor(BG)
        for j,b in enumerate(blocks,1):
            if level(b)==i-1:draw_block_2d(ax,b,j,origin=origin,ghost=True)
        for j,b in enumerate(blocks,1):
            if level(b)==i:draw_block_2d(ax,b,j,origin=origin)
        ax.add_patch(Rectangle((g[0]-origin[0],g[2]-origin[1]),g[1]-g[0],g[3]-g[2],
                              fill=False,linewidth=1.8,edgecolor=PURPLE,linestyle='--',zorder=7))
        ax.axvline(0,color=MAGENTA,linestyle='--',linewidth=1.2,alpha=.85,zorder=7)
        ax.axhline(0,color=MAGENTA,linestyle='--',linewidth=1.2,alpha=.85,zorder=7)
        ax.scatter([0],[0],marker='+',s=70,color=MAGENTA,zorder=8)
        # G is identical in every panel, even when upper bricks are off-axis.
        ax.text(.02,.03,'G: Z-axis projection',transform=ax.transAxes,fontsize=7,color=MAGENTA,
                bbox={'facecolor':'white','edgecolor':'none','alpha':.85,'pad':1},zorder=9)
        for j,b in enumerate(blocks,1):
            if level(b)!=i:continue
            xy=np.array(b['pos'][:2])*1000
            margin=max(g[0]-xy[0],xy[0]-g[1],g[2]-xy[1],xy[1]-g[3])
            qualifies=boundary_centres and i>0 and margin>=-1e-5
            if qualifies:qualifying_ids.append(j)
            cx,cy=xy-origin
            color=ORANGE if qualifies else '#243346'
            ax.scatter([cx],[cy],s=35,c=color,edgecolors='white',linewidths=.8,zorder=8)
            ax.text(cx+3,cy+4,f'C{j}',fontsize=8,color=color,
                    bbox={'facecolor':'white','edgecolor':'none','alpha':.9,'pad':1},zorder=9)
        ax.set_xlim(xmin,xmax);ax.set_ylim(ymin,ymax);ax.set_aspect('equal')
        ax.set_title(f'Layer {i} | body Z = {i*20} mm',fontsize=10,fontweight='bold')
        ax.set_xlabel('X - Gx (mm)',fontsize=8,color=TEAL);ax.set_ylabel('Y - Gy (mm)',fontsize=8,color=TEAL)
        ax.tick_params(labelsize=7);ax.grid(alpha=.15)
    fig.suptitle('Layer plans | one common ground reference G for every layer',fontsize=12,fontweight='bold',y=.98)
    legend=('Magenta cross: Z-axis at ground-envelope midpoint G (not centre of mass).\n'
            'Purple: ground boundary | Gray dashed: previous-layer support | C1...CN: brick centres.\n'
            + tier_caption())
    fig.text(.5,.028,legend,ha='center',va='bottom',fontsize=9,color='#334155')
    fig.subplots_adjust(left=.065,right=.975,top=.91,bottom=.18,wspace=.38,hspace=.48)
    audit_guides('layers',blocks,origin,g,qualifying_ids=qualifying_ids,all_panels_share_reference=True)
    return figure_image(fig)


def draw_center_overlay(blocks):
    """All layer footprints in one XY view, with unchanged world coordinates."""
    xy = np.array([b['pos'][:2] for b in blocks])*1000
    if np.max(np.abs(xy-xy[0]))>1e-6:
        raise ValueError('Cannot mark unaligned input as centre-aligned')
    fig,ax = plt.subplots(figsize=(8,6.6667),dpi=120,facecolor=BG)
    ax.set_facecolor(BG)
    for i,b in enumerate(blocks,1):
        bb=box(b);w,h=dims(b);yaw=round(math.degrees(b['rotation'][2]))%360
        ax.add_patch(Rectangle((bb[0]-xy[0,0],bb[2]-xy[0,1]),w,h,
                              facecolor=COLORS[b['color']],alpha=.08,edgecolor='none'))
        ax.add_patch(Rectangle((bb[0]-xy[0,0],bb[2]-xy[0,1]),w,h,
                              fill=False,edgecolor=COLORS[b['color']],linewidth=2,
                              linestyle='-' if yaw%180==0 else '--',label=f'Brick {i}: yaw {yaw} deg'))
    ax.axhline(0,color='#c026b5',linestyle='--',linewidth=1.4)
    ax.axvline(0,color='#c026b5',linestyle='--',linewidth=1.4)
    ax.scatter([0],[0],marker='+',s=220,color='#c026b5',linewidths=3,zorder=10)
    ax.text(2,2,'ALL centres (0, 0)',color='#a02192',fontsize=11,
            bbox={'facecolor':'white','edgecolor':'none','alpha':.85},zorder=11)
    ax.set_xlim(-42,42);ax.set_ylim(-42,42);ax.set_aspect('equal');ax.grid(alpha=.2)
    ax.set_xlabel('X relative to common centre (mm)');ax.set_ylabel('Y relative to common centre (mm)')
    ax.set_title('Tier 2 | C1...CN share the same Z-axis',fontsize=14,fontweight='bold')
    ax.legend(loc='upper left',bbox_to_anchor=(1.02,1),fontsize=9,facecolor='white',framealpha=.96)
    fig.text(.5,.035,f'Every layer world XY = ({xy[0,0]:g}, {xy[0,1]:g}) mm\nRectangles rotate about this centre; overlapping outlines share exactly the same midpoint.',
             ha='center',fontsize=10,color='#334155')
    fig.subplots_adjust(left=.12,right=.75,top=.9,bottom=.15)
    reference,g=ground_reference(blocks)
    audit_guides('tier2_footprint_overlay',blocks,reference,g)
    return figure_image(fig)


def draw_initial(scene, blocks):
    fig, ax = plt.subplots(figsize=(8, 6.6667), dpi=120, facecolor=BG)
    ax.set_facecolor(BG)
    p = scene['parts_plate']; x, y = np.array(p['center'][:2])*1000
    w, h = np.array(p['size'])*1000
    ax.add_patch(Rectangle((x-w/2, y-h/2), w, h, edgecolor='#8d9aad',
                          facecolor='#e9eef5', linewidth=1.5))
    ids = {b['name']: i for i, b in enumerate(blocks, 1)}
    for b in scene['blocks']:
        draw_block_2d(ax, b, ids[b['name']])
        cx,cy=np.array(b['pos'][:2])*1000
        ax.scatter([cx],[cy],s=28,c='#243346',edgecolors='white',linewidths=.8,zorder=8)
        ax.text(cx+6,cy+5,f'C{ids[b["name"]]}',fontsize=8,color='#243346',
                bbox={'facecolor':'white','edgecolor':'none','alpha':.85,'pad':1},zorder=9)
    ax.axvline(x,color=MAGENTA,linestyle='--',linewidth=1.2,zorder=7)
    ax.axhline(y,color=MAGENTA,linestyle='--',linewidth=1.2,zorder=7)
    ax.text(x+4,y+4,'P: initial plate centre',fontsize=9,color=MAGENTA,
            bbox={'facecolor':'white','edgecolor':'none','alpha':.9,'pad':1},zorder=10)
    ax.set_xlim(x-w/2-12, x+w/2+12); ax.set_ylim(y-h/2-12, y+h/2+12)
    ax.set_aspect('equal'); ax.grid(alpha=.16)
    ax.set_xlabel('World X (mm)'); ax.set_ylabel('World Y (mm)')
    ax.set_title('Initial parts layout | top view', fontsize=14, fontweight='bold')
    ax.tick_params(labelsize=9)
    fig.text(.5, .04, 'Magenta cross: initial parts-plate Z-axis projection P; C IDs match target.\nInitial parts are scattered; this panel does not require coincident centres.',
             ha='center', va='bottom', fontsize=10, color='#334155')
    fig.subplots_adjust(left=.1, right=.96, top=.91, bottom=.15)
    audit_guides('initial_plan',scene['blocks'],np.array([x,y]),None)
    return figure_image(fig)


def font(size):
    for path in ('/System/Library/Fonts/Supplemental/Arial.ttf',
                 '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def detail_panel(front, back, layers, initial, title):
    canvas = Image.new('RGB', (W*2, H*2+100), BG)
    draw = ImageDraw.Draw(canvas)
    draw.text((30, 16), title, font=font(28), fill='#172b45')
    draw.text((30, 55), ('Paper Fig. 1/3-style schematic + YAML plans.' if STYLE == 'paper' else 'Exact STL previews + YAML plans.')+' Static inspection; physics is not simulated.',
              font=font(19), fill='#49596b')
    for pic, xy in zip((front, back, layers, initial), ((0,100), (W,100), (0,H+100), (W,H+100))):
        canvas.paste(pic, xy)
    return canvas


def pair_panel(initial, target, title):
    canvas = Image.new('RGB',(W*2+100,H+95),BG)
    draw = ImageDraw.Draw(canvas)
    draw.text((30,15),title,font=font(27),fill='#172b45')
    draw.text((30,50),'The same bricks before and after assembly; do not add the two panels together.',font=font(20),fill='#49596b')
    canvas.paste(initial,(0,85)); canvas.paste(target,(W+100,85))
    draw.line((W+12,H//2+85,W+84,H//2+85),fill='black',width=3)
    draw.polygon(((W+84,H//2+85),(W+67,H//2+75),(W+67,H//2+95)),fill='black')
    return canvas


def pick_samples(repo, tier):
    root = repo/'versions/latest/tasks'/CLASSES[tier-1]
    directories = sorted(p for p in root.iterdir() if p.is_dir())
    if tier > 2:
        # Typical low-count examples for the 80/15/5 distribution.
        chosen = []
        for n in (3,3,4,4,5,6):
            chosen.append(next(p for p in directories if p not in chosen and
                               load_yaml(p/'metadata.yaml')['num_blocks'] == n))
        return chosen
    if tier == 2:
        # Square bricks hide quarter-turn changes visually. Preview two long-
        # brick crossed stacks per count so the centred 0/90 rule is inspectable.
        chosen = []
        for n in (2,3):
            candidates = []
            for p in directories:
                goal = load_yaml(p/'final_product.yaml')['blocks']
                yaws = {round(math.degrees(b['rotation'][2]))%180 for b in goal}
                if len(goal) == n and goal[0]['type'] == 'brick_4x2' and len(yaws) == 2:
                    candidates.append(p)
            candidates.extend(p for p in directories
                              if p not in candidates and load_yaml(p/'metadata.yaml')['num_blocks'] == n)
            chosen.extend(candidates[:2])
        return chosen
    # Include both brick types and orientations rather than six arbitrary seeds.
    chosen, signatures = [], set()
    for p in directories:
        b = load_yaml(p/'final_product.yaml')['blocks'][0]
        signature = (b['type'], round(math.degrees(b['rotation'][2])) % 180)
        if signature not in signatures:
            chosen.append(p); signatures.add(signature)
    chosen.extend(p for p in directories if p not in chosen)
    return chosen[:6]


def main():
    from render_gallery import main as render_main
    render_main()


if __name__ == '__main__':
    main()
