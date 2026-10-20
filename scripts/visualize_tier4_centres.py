"""Paper-style Tier 4 views with explicit centres against the ground boundary."""
from pathlib import Path
import argparse,csv,hashlib,json,math,shutil,zipfile
import numpy as np
from PIL import Image,ImageDraw
import visualize_task as v
from verifier import verify_instance_dir


def centre_records(blocks):
    _,_,_,g=v.summary(blocks)
    records=[]
    for i,b in enumerate(blocks,1):
        x,y=np.array(b['pos'][:2])*1000
        margin=float(max(g[0]-x,x-g[1],g[2]-y,y-g[3]))
        relation='outside' if margin>1e-5 else ('boundary' if margin>=-1e-5 else 'inside')
        records.append({'id':i,'layer':v.level(b),'world_x_mm':float(x),'world_y_mm':float(y),
                        'signed_center_margin_mm':margin,'relation':relation,'qualifies':v.level(b)>0 and margin>=-1e-5})
    return records,g


def draw_centre_side(blocks):
    records,g=centre_records(blocks)
    long=next(b for b in blocks if b['type']=='brick_4x2');axis=int(v.dims(long)[1]>v.dims(long)[0])
    lo,hi=g[2*axis:2*axis+2];origin=(lo+hi)/2
    boxes=[v.box(b) for b in blocks];xmin=min(q[2*axis] for q in boxes)-origin-28;xmax=max(q[2*axis+1] for q in boxes)-origin+28
    top=max(b['pos'][2]*1000+23.75 for b in blocks)
    fig,ax=v.plt.subplots(figsize=(8,6.6667),dpi=120,facecolor='white');ax.set_facecolor('white')
    for i,b in sorted(enumerate(blocks,1),key=lambda q:q[1]['pos'][2]):
        bb=v.box(b);left,right=bb[2*axis:2*axis+2];z=b['pos'][2]*1000
        ax.add_patch(v.Rectangle((left-origin,z),right-left,20,facecolor=v.COLORS[b['color']],edgecolor='black',linewidth=1.3,zorder=2+v.level(b)))
        for x in np.arange(left+8,right,16):
            ax.add_patch(v.Rectangle((x-origin-4.6,z+20),9.2,3.75,facecolor=v.COLORS[b['color']],edgecolor='black',linewidth=.8,zorder=2+v.level(b)))
    ax.axvline(0,color=v.MAGENTA,linestyle='--',linewidth=1.6,zorder=10)
    ax.text(3,3,'G / Z',fontsize=10,color=v.MAGENTA,zorder=13,
            bbox={'facecolor':'white','edgecolor':'none','alpha':.9,'pad':1})
    for edge in (lo,hi):ax.plot([edge-origin,edge-origin],[0,top+8],color='#8b3fc0',linestyle='--',linewidth=2,zorder=10)
    for r,b in zip(records,blocks):
        x=b['pos'][axis]*1000-origin;z=b['pos'][2]*1000+10
        ax.scatter([x],[z],s=100,c='#f97316' if r['qualifies'] else '#243346',edgecolors='white',linewidths=1.1,zorder=12)
        ax.text(x+5,z+4,f'C{r["id"]}',fontsize=11,fontweight='bold',color='#172b45',
                bbox={'facecolor':'white','edgecolor':'none','alpha':.9,'pad':1},zorder=13)
        if r['qualifies']:
            label=f'C{r["id"]}: CENTRE ON BOUNDARY (0 mm)' if r['relation']=='boundary' else f'C{r["id"]}: CENTRE OUTSIDE ({r["signed_center_margin_mm"]:g} mm)'
            # Put the label on the opposite half, avoiding clipping near an edge.
            tx=(xmin+xmax)/2-10 if x>0 else (xmin+xmax)/2+10
            ax.annotate(label,xy=(x,z),xytext=(tx,top+15),ha='center',fontsize=10,color='#c2410c',
                        arrowprops={'arrowstyle':'->','color':'#c2410c','lw':1.4},
                        bbox={'facecolor':'white','edgecolor':'none','pad':1},zorder=14)
    ax.annotate('',xy=(hi-origin,-7),xytext=(lo-origin,-7),arrowprops={'arrowstyle':'<->','color':'#8b3fc0','lw':1.5})
    ax.text(0,-14,'GROUND BOUNDARY',ha='center',va='center',color='#8b3fc0',fontsize=11)
    ax.set_xlim(xmin,xmax);ax.set_ylim(-22,top+28);ax.set_aspect('equal');ax.grid(alpha=.15)
    ax.set_xlabel(f'{"XY"[axis]} (mm, relative to ground centre)',fontsize=11);ax.set_ylabel('Body Z (mm)',fontsize=11);ax.tick_params(labelsize=9)
    fig.suptitle(f'CENTRE CHECK | {len(blocks)} bricks | C1...CN = brick centres',fontsize=14,fontweight='bold',y=.965)
    fig.text(.5,.055,'Magenta: Z-axis through ground-envelope midpoint G (not centre of mass).\nPurple: ground boundary extended upward | C1...CN: brick centres.\nOrange upper CENTRE must be ON / OUTSIDE the purple boundary.',ha='center',va='center',fontsize=11,color='#243346')
    fig.subplots_adjust(left=.12,right=.97,top=.85,bottom=.23)
    reference,_=v.ground_reference(blocks)
    v.audit_guides('tier4_centre_side',blocks,reference,g,side_axis=axis,qualifying_ids=[r['id'] for r in records if r['qualifies']])
    return v.figure_image(fig),axis,records


def main():
    from render_gallery import main as render_main
    render_main(default_tiers=(4,))


if __name__ == '__main__':
    main()
