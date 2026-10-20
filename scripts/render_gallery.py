#!/usr/bin/env python3
"""Render the current task gallery by tier and instance, without modifying tasks."""
from pathlib import Path
import argparse,csv,hashlib,html,json,math,shutil
from PIL import Image,ImageDraw
import visualize_task as v
import visualize_tier4_centres as c
from verifier import verify_instance_dir

CSS='body{font:16px/1.6 system-ui;max-width:1450px;margin:30px auto;padding:0 20px;background:#f6f8fb;color:#172b45}a{color:#1765b8}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:18px}article,.note{background:white;border:1px solid #dce3ed;border-radius:12px;padding:16px}img{width:100%;height:auto}h3{overflow-wrap:anywhere;font-size:16px}code{background:#edf1f6;padding:2px 5px}'
RULES={1:'恰好 2 块同砖型，XY 中心相同、朝向固定，逐层垂直堆叠。',
       2:'2–5 块（85% 为 2–3 块）同砖型，每层一块、所有 XY 中心完全一致，朝向仅 0°/90°。长砖交叉时砖体可以伸出底砖；判断重点是中心一致。',
       3:'3–12 块，多块底层支撑通过上层桥接连接；所有上层砖的整个底面矩形都在底层整体包络内（允许贴边）。中心不要求重合。',
       4:'3–12 块，至少一块上层砖的 XY 中心落在底层整体包络的边界上或外部。仅砖体伸出而中心仍在内部，不满足此规则。'}
READING={1:'看 C1、C2：两个中心应落在同一条洋红色竖轴上，分层俯视图中都在 G 点，朝向相同。',
         2:'先数 2–5 块（以 2–3 块为主），再看每层 C 点是否都位于 G。共同中心图中，长砖轮廓只能平行重合或相差 90°；不能平移。',
         3:'看分层图：多个底层支撑可以不在 G 点，上层桥接砖的整个矩形仍须留在紫色包络内。灰色虚线是真实下层支撑，紫线中间可能包含空隙。',
         4:'先找橙色的上层 C 点，再比较紫色边界线：C 点必须压在线上或越过线。不是比较砖边，也不是比较洋红色参考轴。'}
LEGEND='<p class="note"><b>统一图例：</b><span style="color:#c026b5">洋红 Z 轴 / 俯视十字</span>：底层包络中点 G 的竖直参考轴；<span style="color:#8b3fc0">紫色虚线</span>：底层整体边界；C1…CN：各砖 XY 中心（3D/侧视中标在砖体半高处）；<span style="color:#f97316">橙点</span>：Tier 4 满足边界规则的上层中心；<span style="color:#087e8b">青色 X/Y</span>：世界坐标正方向。G 不是重心，也不是每块砖必须达到的位置。初始散件图以料盘中心 P 为参考，不要求散件中心重合。隐藏中心也以检查标注显示。</p>'
GROUND_NOTE='底层整体边界 = 所有底层砖的名义底面矩形围成的、与世界 X/Y 轴平行的最小外接矩形；不是单块砖的边界，也不代表空隙处有真实支撑。'


def definition_page(out,tiers,rows):
    table='<table style="width:100%;border-collapse:collapse"><tr><th>Tier</th><th>块数</th><th>判断条件</th></tr>'
    for t in tiers:table+=f'<tr><td><a href="tier_{t}/index.html">Tier {t}</a></td><td>{"2" if t==1 else "2–5（主要 2–3）" if t==2 else "3–12"}</td><td>{RULES[t]}</td></tr>'
    table+='</table>'
    body='<p><a href="index.html">返回最新版图片</a></p>'+LEGEND+f'<p class="note">{GROUND_NOTE}</p>'+table
    body+='<p>这是当前版本的任务定义。Tier 2 使用小块数分布与独立直角朝向，Tier 4 将上层中心位于底层包络边界纳入合格条件；这些生成约定与原论文的任务设置分别记录。</p><p>Tier 2 完整 100 个任务：2 块 43 个、3 块 42 个、4 块 8 个、5 块 7 个。2 块且同朝向的 Tier 2 样例可能与 Tier 1 外观相同；Tier 2 采用独立 0°/90° 朝向策略，类别不能仅凭块数区分。</p><p>Tier 3/4 当前生成策略：最多三层、直线且平行；每个 Tier 的完整 100 个任务为 80% 3–5 块、15% 6–8 块、5% 9–12 块。这是简化形状与数量分布策略，不是中心判断的替代条件。</p>'
    for t in tiers:
        r=next(r for r in rows if r['tier']==t and r['featured']);folder=r['image_directory'];second='center_side.png' if t==4 else 'layers.png'
        body+=f'<details open class="note"><summary><b>Tier {t} · {r["instance_id"]} · {r["num_blocks"]} 块</b></summary><p>{READING[t]}</p><div class="grid"><a href="{folder}/target.png"><img src="{folder}/target.png" alt="Tier {t} 标注三维图"></a><a href="{folder}/{second}"><img src="{folder}/{second}" alt="Tier {t} 标注分层或侧视图"></a></div><p><a href="tier_{t}/index.html">检查该 Tier 的全部样例</a></p></details>'
    body+='<p class="note"><b>Tier 3 与 Tier 4 的区别：</b>Tier 3 比较整个上层砖底面与底层包络，Tier 4 比较上层砖中心与底层包络。Tier 3 允许砖边贴线；Tier 4 要求上层中心贴线或越线。结构参考轴 G 不是两者的分类边界。当前几何检查不等于物理平衡或实际装配顺序的认证。</p>'
    (out/'tier_definitions.html').write_text(page('四个 Tier 的定义与标注读图',body))


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def page(title,body):return f'<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title><style>{CSS}</style><h1>{html.escape(title)}</h1>{body}</html>'
def write_csv(path,rows):
    with path.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

def choose(repo,tier,count):
    paths=sorted((repo/'versions/latest/tasks'/v.CLASSES[tier-1]).glob('*/metadata.yaml'))
    directories=[p.parent for p in paths];chosen=[]
    if tier==1:chosen=v.pick_samples(repo,tier)
    elif tier==2:
        for n,quota in ((2,5),(3,5),(4,1),(5,1)):
            group=[p for p in directories if v.load_yaml(p/'metadata.yaml')['num_blocks']==n]
            crossed=[];square=[];parallel=[]
            for p in group:
                b=v.load_yaml(p/'final_product.yaml')['blocks'];yaws={round(math.degrees(q['rotation'][2]))%180 for q in b}
                (square if b[0]['type']=='brick_2x2' else crossed if len(yaws)>1 else parallel).append(p)
            selected=crossed[:2]+square[:1]+parallel[:1]
            selected.extend(p for p in group if p not in selected)
            chosen.extend(selected[:quota])
    else:
        for n in (3,4,5,3,4,5,3,4,5,6,8,9):
            chosen.append(next(p for p in directories if p not in chosen and v.load_yaml(p/'metadata.yaml')['num_blocks']==n))
    chosen.extend(p for p in directories if p not in chosen)
    return chosen[:count]

def overview(output,tier,rows,filename,frame,subtitle):
    columns=3;tile_h=v.H+42;height=math.ceil(len(rows)/columns)*tile_h+120
    sheet=Image.new('RGB',(v.W*columns,height),'white');d=ImageDraw.Draw(sheet)
    d.text((30,18),f'TIER {tier} | {len(rows)} featured tasks | latest dataset',font=v.font(36),fill='#172b45')
    d.text((30,68),subtitle,font=v.font(25),fill='#49596b')
    for i,row in enumerate(rows):
        x=(i%columns)*v.W;y=(i//columns)*tile_h+120
        d.text((x+20,y+5),f'{row["instance_id"]} | {row["num_blocks"]} bricks',font=v.font(22),fill='#172b45')
        with Image.open(output/row['instance_id']/frame) as im:sheet.paste(im,(x,y+42))
    sheet.save(output/filename)

def card(row,tier):
    name=row['instance_id'];prefix=html.escape(name);thumbnail='center_side.png' if tier==4 else 'target.png'
    links=[]
    for key,label in [('target.png','目标三维图'),('initial_to_target.png','初始 → 目标'),('layers.png','分层 XY 图'),('inspection.png','四图检查'),('center_check.png','共同中心检查'),('center_side.png','中心侧视图'),('center_inspection.png','三维＋中心边界')]:
        if key in json.loads(row['image_files']):links.append(f'<a href="{prefix}/{key}">{label}</a>')
    links.append(f'<a href="{prefix}/source/final_product.yaml">对应目标 YAML</a>')
    return f'<article><a href="{prefix}/{thumbnail}"><img loading="lazy" src="{prefix}/{thumbnail}" alt="{prefix}"></a><h3>{prefix}</h3><p>{row["num_blocks"]} 块 · seed {row["seed"]} · {row["layers"]} 层</p><p>'+ ' · '.join(links)+'</p></article>'

def main(default_tiers=(1,2,3,4)):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--repo',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--samples-per-tier',type=int,default=12);p.add_argument('--tiers',nargs='+',type=int,choices=(1,2,3,4),default=list(default_tiers));p.add_argument('--style',choices=('paper','stl'),default='paper')
    a=p.parse_args();repo=a.repo.resolve();out=a.output.resolve();tiers=sorted(set(a.tiers));tasks=repo/'versions/latest/tasks'
    if not 1<=a.samples_per_tier<=100:p.error('--samples-per-tier must be 1..100')
    if out.exists() or out==repo or any(out.is_relative_to(repo/q) for q in ('tasks','versions/latest/tasks','versions/initial','assets','scripts','tests')):p.error('Use a fresh separate output directory')
    before={str(q.relative_to(tasks)):sha(q) for q in tasks.rglob('*.yaml')};featured={t:choose(repo,t,a.samples_per_tier) for t in tiers}
    out.mkdir(parents=True);v.STYLE=a.style;v.BG='white'
    if a.style=='paper':v.COLORS=v.PAPER_COLORS.copy()
    meshes={t:v.paper_mesh(t) if a.style=='paper' else v.load_mesh(repo/'assets/meshes'/f'LEGO_Duplo_{t}.stl',t) for t in ('brick_2x2','brick_4x2')}
    rows=[];center_rows=[]
    for tier in tiers:
        folder=out/f'tier_{tier}';folder.mkdir();featured_names={q.name for q in featured[tier]}
        sources=sorted((tasks/v.CLASSES[3]).iterdir()) if tier==4 else featured[tier]
        sources=[q for q in sources if q.is_dir()]
        for number,source in enumerate(sources,1):
            ok,errors=verify_instance_dir(source)
            if not ok:raise ValueError(f'{source}: {errors}')
            name=source.name;dest=folder/name;dest.mkdir();blocks=v.load_yaml(source/'final_product.yaml')['blocks'];meta=v.load_yaml(source/'metadata.yaml')
            v.GUIDE_CONTEXT={'tier':tier,'instance_id':name}
            nlevels,support,_,_=v.summary(blocks);is_featured=name in featured_names;frames=[]
            if tier==4:
                records,_=c.centre_records(blocks);qual=[r['id'] for r in records if r['qualifies']]
                if not qual:raise ValueError(f'{name}: no qualifying upper centre')
                for r in records:center_rows.append({'instance_id':name,**r})
                side,axis,_=c.draw_centre_side(blocks);side.save(dest/'center_side.png');v.draw_layers(blocks,boundary_centres=True).save(dest/'layers.png')
                front=v.draw_mesh(blocks,meshes,f'{name} | upper centre on ground boundary',-90 if axis==0 else 0,elevation=20,boundary_centres=True)
                panel=Image.new('RGB',(v.W*2,v.H+100),'white');d=ImageDraw.Draw(panel)
                d.text((25,15),f'TIER 4 | {name} | {len(blocks)} bricks | qualifying centre C{qual[-1]}',font=v.font(26),fill='#172b45')
                d.text((25,55),'Magenta: reference Z-axis. Orange centre ON / OUTSIDE purple ground boundary.',font=v.font(23),fill='#49596b');panel.paste(front,(0,100));panel.paste(side,(v.W,100));panel.save(dest/'center_inspection.png')
                frames.extend(['center_side.png','layers.png','center_inspection.png'])
            if is_featured:
                title=f'{name} | {len(blocks)} bricks | {nlevels} layers | min support {support:.0%}'
                front=v.draw_mesh(blocks,meshes,title,-60 if a.style=='paper' else -55,center_guides=tier==2,boundary_centres=tier==4);front.save(dest/'target.png')
                back=v.draw_mesh(blocks,meshes,'Target assembly | reverse view',120 if a.style=='paper' else 125,center_guides=tier==2,boundary_centres=tier==4)
                scene=v.load_yaml(source/'scene_init.yaml');initial=v.draw_mesh(scene['blocks'],meshes,'Initial parts arrangement',-60,reference_xy=scene['parts_plate']['center'][:2],brick_ids={b['name']:i for i,b in enumerate(blocks,1)})
                v.pair_panel(initial,front,title).save(dest/'initial_to_target.png')
                if tier!=4:v.draw_layers(blocks,center_guides=tier in (1,2)).save(dest/'layers.png');frames.append('layers.png')
                with Image.open(dest/'layers.png') as im:layers=im.copy()
                v.detail_panel(front,back,layers,v.draw_initial(scene,blocks),title).save(dest/'inspection.png')
                frames.extend(['target.png','initial_to_target.png','inspection.png'])
                if tier==2:
                    side=v.draw_mesh(blocks,meshes,'Same XY centre | 0 / 90 degrees',-90,center_guides=True,elevation=0)
                    v.detail_panel(front,side,v.draw_center_overlay(blocks),layers,title).save(dest/'center_check.png');frames.append('center_check.png')
            copy=dest/'source';copy.mkdir();hashes={}
            for f in ('final_product.yaml','scene_init.yaml','metadata.yaml'):shutil.copy2(source/f,copy/f);hashes[f]=sha(source/f)
            rows.append({'tier':tier,'instance_id':name,'num_blocks':len(blocks),'seed':meta['seed'],'layers':nlevels,'min_support_ratio':round(support,8),'featured':is_featured,
                         'source_path':source.relative_to(repo).as_posix(),'source_sha256':json.dumps(hashes,sort_keys=True),'image_files':json.dumps(frames),'image_directory':f'tier_{tier}/{name}',
                         'stack_yaw_policy':meta.get('stack_yaw_policy',''),'shape_policy':meta.get('shape_policy',''),'center_boundary_policy':meta.get('center_boundary_policy','')})
            print(f'Tier {tier}: {number}/{len(sources)} {name}',flush=True)
        group=[r for r in rows if r['tier']==tier];examples=[next(r for r in group if r['instance_id']==q.name) for q in featured[tier]]
        overview(folder,tier,examples,'overview.png','target.png','TOTAL is the brick count. Different views show the same task.')
        if tier==4:overview(folder,tier,examples,'center_overview.png','center_side.png','Orange dots: qualifying upper centres. Purple lines: ground boundary.')
        body=f'<p><a href="../index.html">返回四个 Tier 总入口</a></p><p class="note">{RULES[tier]} 所有图片从当前 YAML 渲染；不同视图展示同一任务。任务本体在 <code>versions/latest/tasks/{v.CLASSES[tier-1]}/</code>。采用论文风格，保留原始积木位置、朝向、类型、颜色。</p><p><a href="overview.png">{len(examples)} 例目标总览</a>'
        if tier==4:body+=' · <a href="center_overview.png">中心边界总览</a> · <a href="brick_center_coordinates.csv">全部中心坐标</a>'
        body+=f'</p><p><a href="../tier_definitions.html">四个 Tier 定义与标注读图</a></p>'+LEGEND+f'<p class="note">{GROUND_NOTE}<br>{READING[tier]}</p><h2>先检查这 {len(examples)} 个样例</h2><div class="grid">'+''.join(card(r,tier) for r in examples)+'</div>'
        if tier==4:body+='<h2>全部 100 个 Tier 4 中心检查</h2><div class="grid">'+''.join(card(r,tier) for r in group)+'</div>'
        (folder/'index.html').write_text(page(f'Tier {tier} · 最新版多视图检查',body));write_csv(folder/'manifest.csv',group)
        (folder/'README.md').write_text(f'# Tier {tier}\n\n{RULES[tier]}\n\n统一图例和定义：../tier_definitions.html。洋红色是结构参考轴 G，紫色是底层包络，C 编号是砖中心，橙点是 Tier 4 合格上层中心。G 不表示重心；初始图使用料盘参考 P。\n\n从 index.html 进入；overview.png 显示 {len(examples)} 个样例。每个任务使用实例 ID 命名的独立目录；文件名表示视角。source/ 是对应 YAML 检查副本。完整任务在 versions/latest/tasks/{v.CLASSES[tier-1]}/。\n')
    if center_rows:write_csv(out/'tier_4/brick_center_coordinates.csv',center_rows)
    write_csv(out/'manifest.csv',rows)
    cards=''.join(f'<article><a href="tier_{t}/index.html"><img src="tier_{t}/overview.png" alt="Tier {t}"></a><h2>Tier {t}</h2><p>{RULES[t]}</p><p><a href="tier_{t}/index.html">打开 {a.samples_per_tier} 例多视图检查'+('与全部 100 例中心检查' if t==4 else '')+'</a></p></article>' for t in tiers)
    (out/'index.html').write_text(page('最新版图片 · 按 Tier 和任务整理',f'<p><a href="tier_definitions.html">先看四个 Tier 定义与标注读图</a></p>'+LEGEND+f'<p class="note">每个 Tier 提供 {a.samples_per_tier} 个精选样例，每例至少 4 张不同视角/阶段的检查图；Tier 4 另保留全部 100 个任务的中心边界检查。Tier 2 以 2–3 块为主（完整数据 85%，4–5 块为 15%）；Tier 3/4 以 3–5 块为主（完整数据 80% / 15% / 5%）。凸点不计作额外积木。</p><div class="grid">{cards}</div><p><a href="manifest.csv">图像与任务对应清单</a> · <a href="README.md">目录说明</a></p>'))
    (out/'README.md').write_text(f'# 最新版图片\n\n[tier_definitions.html](tier_definitions.html) 解释四个 Tier 与全部颜色标注。洋红色竖轴通过底层整体包络中点 G；俯视图中为十字。G 不表示重心。紫线是底层包络边界，C 点是每块砖的真实 XY 中心，橙点是满足 Tier 4 规则的上层中心。初始散件图用料盘参考 P。\n\n每个 Tier 有独立 tier_1/…tier_4/ 目录，每个精选样例至少四张图。每个任务使用完整实例 ID 命名，里面 target.png / initial_to_target.png / layers.png / inspection.png 分别是目标三维图、初始到目标、分层图和四图检查。Tier 2 有 center_check.png；Tier 4 有 center_side.png 和 center_inspection.png。\n\n当前每 Tier 精选 {a.samples_per_tier} 例；Tier 4 全部 100 例也包含中心检查。source/ 只用于对照图片；任务本体在 ../tasks/。默认按 symposium paper 风格绘制，静态图不认证接触物理。\n\n重新生成到新目录：python scripts/render_gallery.py --output /tmp/benchmark_gallery_new\n')
    assert before=={str(q.relative_to(tasks)):sha(q) for q in tasks.rglob('*.yaml')}
    definition_page(out,tiers,rows)
    (out/'structure_axis_audit.json').write_text(json.dumps(v.AXIS_AUDIT,indent=2)+'\n')
    (out/'rendered_mesh_centres.json').write_text(json.dumps(v.CENTRE_AUDIT,indent=2)+'\n')
    report={'instances_with_images':len(rows),'featured_samples_per_tier':a.samples_per_tier,'tier_image_instances':{str(t):sum(r['tier']==t for r in rows) for t in tiers},
            'png_files':len(list(out.rglob('*.png'))),'source_yaml_hash_matches':len(rows)*3,'task_yaml_modified':False,'style':a.style,'tier4_cached_source_verified':0,'annotation_version':v.ANNOTATION_VERSION,'annotated_view_records':len(v.AXIS_AUDIT),
            'renderer_source_sha256':sha(Path(__file__)),'mesh_helper_source_sha256':sha(Path(v.__file__)),'centre_helper_source_sha256':sha(Path(c.__file__)),'remote_writes':False}
    (out/'preview_validation.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2),flush=True)

if __name__=='__main__':main()
