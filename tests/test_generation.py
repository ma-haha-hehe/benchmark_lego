"""Regression tests for real audit failures and the generated task contracts."""
import copy
import itertools
import math
import random
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import generator
import geometry
import verifier


class GenerationTests(unittest.TestCase):
    def test_all_counts_and_seed_reproduction(self):
        for task_class in geometry.TASK_CLASSES:
            counts = [2] if task_class == 'two_brick_stack' else ([2,3,4,5] if task_class == 'simple_multi_brick_stack' else range(3,13))
            for n in counts:
                for seed in range(10):
                    with self.subTest(task_class=task_class, n=n, seed=seed):
                        data = generator.generate_instance_data(task_class,1,seed,n_blocks=n)
                        self.assertEqual(data,generator.generate_instance_data(task_class,1,seed,n_blocks=n))
                        self.assertTrue(verifier.verify_instance_data(*data)[0])
                        blocks = data[0]['blocks']
                        self.assertEqual(len(blocks),n)
                        # Independently check vertical support from nominal rectangles.
                        for b in blocks:
                            width,height = (0.064,0.032) if b['type']=='brick_4x2' else (0.032,0.032)
                            if round(math.degrees(b['rotation'][2]))%180 == 90:
                                width,height = height,width
                            if b['pos'][2] == 0:
                                continue
                            covered = 0
                            for q in blocks:
                                if abs(b['pos'][2]-q['pos'][2]-0.020)>1e-8:
                                    continue
                                qw,qh = (0.064,0.032) if q['type']=='brick_4x2' else (0.032,0.032)
                                if round(math.degrees(q['rotation'][2]))%180 == 90:
                                    qw,qh = qh,qw
                                dx=max(0,min(b['pos'][0]+width/2,q['pos'][0]+qw/2)-max(b['pos'][0]-width/2,q['pos'][0]-qw/2))
                                dy=max(0,min(b['pos'][1]+height/2,q['pos'][1]+qh/2)-max(b['pos'][1]-height/2,q['pos'][1]-qh/2))
                                covered+=dx*dy
                            self.assertGreaterEqual(covered/(width*height),0.5-1e-8)
                        self.assertFalse(data[2]['planner_checked'])
                        self.assertEqual(len(data[2]['static_assembly_order']),n)

    def test_mesh_dimensions_agree_with_stud_pitch(self):
        for name,expected in [('2x2',(0.032,0.032)),('4x2',(0.064,0.032))]:
            raw=(ROOT/f'assets/meshes/LEGO_Duplo_brick_{name}.stl').read_bytes()
            n=struct.unpack_from('<I',raw,80)[0]
            vertices=[]
            for i in range(n):
                values=struct.unpack_from('<12fH',raw,84+50*i)
                vertices.extend([values[3:6],values[6:9],values[9:12]])
            self.assertEqual(len(raw),84+50*n)
            for axis in range(2):
                extent=(max(v[axis] for v in vertices)-min(v[axis] for v in vertices))*.001
                self.assertAlmostEqual(extent,expected[axis]-.0004,places=7)
            self.assertEqual(geometry.dims_xy('brick_'+name,0),expected)

    def test_default_counts_match_80_15_5_quotas(self):
        for task_class in geometry.TASK_CLASSES[2:]:
            counts=[generator._scheduled_count(task_class,i) for i in range(1,101)]
            self.assertEqual(sum(3 <= n <= 5 for n in counts),80)
            self.assertEqual(sum(6 <= n <= 8 for n in counts),15)
            self.assertEqual(sum(9 <= n <= 12 for n in counts),5)
            self.assertEqual(set(counts),set(range(3,13)))
            self.assertEqual(counts,[generator._scheduled_count(task_class,i) for i in range(101,201)])
            for start in range(0,100,20):
                self.assertEqual(sum(3 <= n <= 5 for n in counts[start:start+20]),16)

    def test_tier2_defaults_prefer_two_and_three_bricks(self):
        counts=[generator._scheduled_count('simple_multi_brick_stack',i) for i in range(1,101)]
        self.assertEqual({n:counts.count(n) for n in set(counts)},{2:43,3:42,4:8,5:7})
        self.assertEqual(counts,[generator._scheduled_count('simple_multi_brick_stack',i) for i in range(101,201)])
        for start in range(0,100,20):
            self.assertEqual(sum(n in (2,3) for n in counts[start:start+20]),17)

    def test_random_tier2_counts_match_small_stack_preference(self):
        class BucketRandom:
            def __init__(self,bucket):self.bucket=bucket
            def randrange(self,stop):return self.bucket
            def randint(self,low,high):return (low,high)
        for bucket in range(100):
            self.assertEqual(generator._sample_stack_count(BucketRandom(bucket)),(2,3) if bucket<85 else (4,5))

    def test_random_shape_counts_use_the_same_bucket_thresholds(self):
        class BucketRandom:
            def __init__(self,bucket): self.bucket = bucket
            def randrange(self,stop):
                self.assert_stop = stop
                return self.bucket
            def randint(self,low,high): return (low,high)
        for bucket in range(100):
            rng=BucketRandom(bucket)
            expected=(3,5) if bucket < 80 else ((6,8) if bucket < 95 else (9,12))
            self.assertEqual(generator._sample_shape_count(rng),expected)
            self.assertEqual(rng.assert_stop,100)

    def test_shape_policy_stays_simple_for_every_permitted_count(self):
        for task_class in geometry.TASK_CLASSES[2:]:
            for n in range(3,13):
                for seed in range(10):
                    with self.subTest(task_class=task_class,n=n,seed=seed):
                        goal,scene,meta=generator.generate_instance_data(task_class,1,seed,n_blocks=n)
                        blocks=goal['blocks']
                        self.assertEqual(meta['shape_policy'],geometry.SHAPE_POLICY)
                        self.assertLessEqual(len({b['pos'][2] for b in blocks}),3)
                        yaw={round(math.degrees(b['rotation'][2]))%180 for b in blocks}
                        self.assertEqual(len(yaw),1)
                        axis=1 if next(iter(yaw)) == 0 else 0
                        self.assertEqual(len({b['pos'][axis] for b in blocks}),1)
                        # Every nominal press centre remains inside the base envelope.
                        ground=[b for b in blocks if b['pos'][2] == 0]
                        base=[verifier.parse_bricks([b])[0].bbox_xy() for b in ground]
                        for b in blocks:
                            self.assertLessEqual(min(q[0] for q in base)-1e-8,b['pos'][0])
                            self.assertLessEqual(b['pos'][0],max(q[1] for q in base)+1e-8)
                            self.assertLessEqual(min(q[2] for q in base)-1e-8,b['pos'][1])
                            self.assertLessEqual(b['pos'][1],max(q[3] for q in base)+1e-8)

    def test_dense_scene_fallback_preserves_clearance(self):
        class FailRandomSampling(random.Random):
            def uniform(self,a,b):
                return (a+b)/2
        bricks=[geometry.Brick(f'b{i}','brick_4x2','red',[0,0,0],[0,0,0]) for i in range(12)]
        scene=generator.sample_scene_init(bricks,FailRandomSampling(1),.03)
        self.assertEqual(len(scene),12)
        for i,a in enumerate(scene):
            for b in scene[i+1:]:
                self.assertGreaterEqual(geometry.rect_distance(a,b),.03-1e-8)

    def test_no_silent_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            generator.generate_instance(folder,'two_brick_stack',1,0,3,False)
            path=Path(folder)/'two_brick_stack/two_brick_stack_001/final_product.yaml'
            original=path.read_bytes()
            with self.assertRaises(FileExistsError):
                generator.generate_instance(folder,'two_brick_stack',1,1,3,False)
            self.assertEqual(path.read_bytes(),original)

    def test_planner_cannot_be_falsely_certified(self):
        with self.assertRaisesRegex(ValueError,'planner'):
            generator.generate_instance_data('two_brick_stack',1,0,use_planner=True)


class VerifierCounterexampleTests(unittest.TestCase):
    def setUp(self):
        self.data=generator.generate_instance_data('two_brick_stack',1,42,n_blocks=2)

    def reject(self,edit,expected):
        data=copy.deepcopy(self.data)
        edit(data)
        ok,errors=verifier.verify_instance_data(*data)
        self.assertFalse(ok)
        self.assertIn(expected,'; '.join(errors))

    def test_overlap_is_rejected(self):
        self.reject(lambda d:d[0]['blocks'][1]['pos'].__setitem__(2,0),'collision')

    def test_floating_is_rejected(self):
        def edit(data):
            for b in data[0]['blocks']:b['pos'][2]+=1
        self.reject(edit,'support ratio')

    def test_roll_is_rejected(self):
        self.reject(lambda d:d[0]['blocks'][1]['rotation'].__setitem__(0,math.pi/2),'roll and pitch')

    def test_shifted_stack_is_rejected(self):
        self.reject(lambda d:d[0]['blocks'][1]['pos'].__setitem__(0,d[0]['blocks'][1]['pos'][0]+.016),'centre-aligned')

    def test_invalid_type_and_malformed_poses_do_not_crash(self):
        self.reject(lambda d:d[0]['blocks'][0].__setitem__('type','bad'),'invalid type')
        self.reject(lambda d:d[0]['blocks'][0].__setitem__('pos',None),'finite numbers')
        self.reject(lambda d:d[0].__setitem__('blocks',None),'nonempty list')
        self.reject(lambda d:d[0]['blocks'][0]['pos'].__setitem__(0,float('nan')),'finite numbers')

    def test_scene_overlap_and_below_minimum_clearance(self):
        self.reject(lambda d:d[1]['blocks'][1].__setitem__('pos',d[1]['blocks'][0]['pos'][:]),'clearance')
        self.reject(lambda d:d[1].__setitem__('min_distance_m',.02),'at least 0.03')

    def test_legacy_geometry_is_explicitly_rejected(self):
        self.reject(lambda d:d[1].pop('geometry'),'regenerate legacy tasks')

    def test_wrong_witness_is_rejected(self):
        self.reject(lambda d:d[2]['static_assembly_order'].reverse(),'static_assembly_order')

    def test_metadata_checked_against_directory(self):
        ok,errors=verifier.verify_instance_data(*self.data,expected_id='wrong',expected_class='simple_shape_assembly')
        self.assertFalse(ok)
        self.assertIn('metadata instance_id does not match directory',errors)
        self.assertIn('metadata task_class does not match directory',errors)

    def test_tier4_rejects_tier3_centres_inside(self):
        data=list(generator.generate_instance_data('simple_shape_assembly',1,2,n_blocks=3))
        data[2]['task_class']='balanced_order_sensitive'
        data[2]['center_boundary_policy']=geometry.TIER4_CENTER_POLICY
        ok,errors=verifier.verify_instance_data(*data)
        self.assertFalse(ok)
        self.assertIn('Tier 4 requires','; '.join(errors))

    def test_shape_policy_cannot_claim_legacy_or_complex_layouts(self):
        original=generator.generate_instance_data('balanced_order_sensitive',1,3001,n_blocks=4)
        edits=[(lambda d:d[2].pop('shape_policy'),'shape_policy'),
               (lambda d:d[0]['blocks'][-1]['pos'].__setitem__(2,.06),'at most three layers'),
               (lambda d:d[0]['blocks'][-1]['rotation'].__setitem__(2,
                    d[0]['blocks'][-1]['rotation'][2]+math.pi/2),'parallel brick footprints')]
        for edit,message in edits:
            data=copy.deepcopy(original)
            edit(data)
            ok,errors=verifier.verify_instance_data(*data)
            self.assertFalse(ok)
            self.assertIn(message,'; '.join(errors))

    def test_duplicate_yaml_keys_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'bad.yaml'
            path.write_text('blocks: []\nblocks: []\n')
            with self.assertRaisesRegex(ValueError,'Duplicate YAML key'):
                verifier.load_yaml(path)


class Tier4CentreBoundaryTests(unittest.TestCase):
    def test_every_count_and_seed_has_an_upper_centre_on_the_boundary(self):
        for n in range(3,13):
            for seed in range(20):
                with self.subTest(n=n,seed=seed):
                    data=generator.generate_instance_data('balanced_order_sensitive',1,seed,n_blocks=n)
                    bricks=verifier.parse_bricks(data[0]['blocks'])
                    bounds=geometry.ground_bbox(bricks)
                    upper=[b for b in bricks if geometry.layer(b)>0]
                    self.assertTrue(geometry.has_upper_center_on_or_outside_ground_boundary(bricks))
                    self.assertAlmostEqual(max(geometry.center_boundary_margin(b,bounds) for b in upper),0)
                    self.assertEqual(data[2]['center_boundary_policy'],geometry.TIER4_CENTER_POLICY)

    def test_footprint_overhang_with_all_centres_inside_is_rejected(self):
        data=list(generator.generate_instance_data('balanced_order_sensitive',1,3000,n_blocks=3))
        # Restore the exact old error: crossed/long footprint protrudes, but all
        # brick centres sit inside the ground rectangle.
        data[0]['blocks'][-1]['pos'][:2]=data[0]['blocks'][0]['pos'][:2]
        bricks=verifier.parse_bricks(data[0]['blocks'])
        self.assertTrue(geometry.has_external_overhang(bricks))
        self.assertFalse(geometry.has_upper_center_on_or_outside_ground_boundary(bricks))
        ok,errors=verifier.verify_instance_data(*data)
        self.assertFalse(ok)
        self.assertIn('centre on or outside','; '.join(errors))

    def test_edge_and_outside_centres_are_accepted_in_all_four_directions(self):
        class PoseRandom(random.Random):
            def __init__(self,turns):super().__init__(0);self.turns=turns
            def randrange(self,*args):
                return self.turns if args==(4,) else super().randrange(*args)
        plate={'center':list(generator.DEFAULT_ASSEMBLY_PLATE_CENTER),'size':list(generator.ASSEMBLY_PLATE_SIZE)}
        for turns in range(4):
            with self.subTest(turns=turns):
                bricks=generator.generate_balanced_order_sensitive(PoseRandom(turns),3)
                bounds=geometry.ground_bbox(bricks)
                top=bricks[-1];base=bricks[0]
                self.assertAlmostEqual(geometry.center_boundary_margin(top,bounds),0)
                self.assertEqual(verifier.verify_goal_geometry(bricks,plate,'balanced_order_sensitive'),[])
                axis=max(range(2),key=lambda i:abs(top.pos[i]-base.pos[i]))
                direction=1 if top.pos[axis]>base.pos[axis] else -1
                top.pos[axis]=round(top.pos[axis]+direction*.016,6)
                self.assertAlmostEqual(geometry.center_boundary_margin(top,bounds),.016)
                self.assertEqual(verifier.verify_goal_geometry(bricks,plate,'balanced_order_sensitive'),[])

    def test_revised_centre_policy_is_required(self):
        data=list(generator.generate_instance_data('balanced_order_sensitive',1,3000,n_blocks=3))
        data[2].pop('center_boundary_policy')
        ok,errors=verifier.verify_instance_data(*data)
        self.assertFalse(ok)
        self.assertIn('center_boundary_policy','; '.join(errors))



class Tier2QuarterTurnTests(unittest.TestCase):
    def test_every_yaw_pattern_and_plate_edge_preserves_one_centre(self):
        class StackRandom(random.Random):
            def __init__(self, brick_type, yaws, high_edge):
                super().__init__(0)
                self.brick_type = brick_type
                self.yaws = iter(yaws)
                self.high_edge = high_edge

            def choice(self, values):
                if values == ['brick_2x2','brick_4x2']:
                    return self.brick_type
                if values == [0,90]:
                    return next(self.yaws)
                return 'red'

            def randint(self, low, high):
                return high if self.high_edge else low

        plate = {'center':list(generator.DEFAULT_ASSEMBLY_PLATE_CENTER),
                 'size':list(generator.ASSEMBLY_PLATE_SIZE)}
        for n in (2,3,4,5):
            for pattern in itertools.product((0,90),repeat=n):
                for brick_type in ('brick_2x2','brick_4x2'):
                    for high_edge in (False,True):
                        with self.subTest(n=n,yaws=pattern,type=brick_type,high_edge=high_edge):
                            bricks = generator.generate_simple_multi_brick_stack(
                                StackRandom(brick_type,pattern,high_edge),n)
                            self.assertEqual({tuple(b.pos[:2]) for b in bricks},
                                             {tuple(bricks[0].pos[:2])})
                            self.assertEqual([b.yaw_deg() for b in bricks],list(pattern))
                            self.assertEqual([b.pos[2] for b in bricks],
                                             [round(i*.02,6) for i in range(n)])
                            self.assertEqual(verifier.verify_goal_geometry(
                                bricks,plate,'simple_multi_brick_stack'),[])
                            for below,above in zip(bricks,bricks[1:]):
                                expected = .5 if brick_type=='brick_4x2' and below.yaw_deg()!=above.yaw_deg() else 1.
                                self.assertAlmostEqual(geometry.support_ratio(above,[below]),expected)

    def crossed_data(self):
        for seed in range(20):
            data = generator.generate_instance_data('simple_multi_brick_stack',1,seed,n_blocks=4)
            if data[0]['blocks'][0]['type']=='brick_4x2':
                break
        for i,b in enumerate(data[0]['blocks']):
            b['pos'][:2] = [0.,.164]
            b['rotation'][2] = (i%2)*math.pi/2
        return data

    def test_centred_cross_is_accepted_but_45_degrees_is_rejected(self):
        data = self.crossed_data()
        self.assertTrue(verifier.verify_instance_data(*data)[0])
        data[0]['blocks'][1]['rotation'][2] = math.pi/4
        ok,errors = verifier.verify_instance_data(*data)
        self.assertFalse(ok)
        self.assertIn('multiple of pi/2','; '.join(errors))

    def test_quarter_turn_does_not_allow_a_shifted_centre(self):
        data = self.crossed_data()
        data[0]['blocks'][1]['pos'][0] += .016
        ok,errors = verifier.verify_instance_data(*data)
        self.assertFalse(ok)
        self.assertIn('centre-aligned','; '.join(errors))

    def test_tier1_still_requires_fixed_yaw(self):
        data = generator.generate_instance_data('two_brick_stack',1,42,n_blocks=2)
        data[0]['blocks'][1]['rotation'][2] += math.pi/2
        ok,errors = verifier.verify_instance_data(*data)
        self.assertFalse(ok)
        self.assertIn('fixed yaw','; '.join(errors))

    def test_tier2_records_and_requires_revised_policy(self):
        data = generator.generate_instance_data('simple_multi_brick_stack',1,0,n_blocks=3)
        self.assertEqual(data[2]['stack_yaw_policy'],'independent_0_90_v1')
        del data[2]['stack_yaw_policy']
        ok,errors = verifier.verify_instance_data(*data)
        self.assertFalse(ok)
        self.assertIn('stack_yaw_policy','; '.join(errors))


class CliTests(unittest.TestCase):
    def call(self,script,*args):
        return subprocess.run([sys.executable,str(ROOT/'scripts'/script),*args],capture_output=True,text=True,timeout=15)

    def test_impossible_clearance_is_bounded_and_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            result=self.call('generator.py','--task_class','two_brick_stack','--num_samples','1',
                             '--min_distance_cm','100','--max_attempts','1','--output_dir',folder)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('after 1 attempts',result.stderr)

    def test_invalid_arguments_fail(self):
        for args in [('--num_samples','0'),('--use_planner',),('--min_distance_cm','nan'),('--num_blocks','12')]:
            with self.subTest(args=args):
                result=self.call('generator.py','--task_class','two_brick_stack',*args)
                self.assertNotEqual(result.returncode,0)

    def test_tier2_cli_accepts_two_bricks_and_rejects_counts_outside_range(self):
        with tempfile.TemporaryDirectory() as folder:
            result=self.call('generator.py','--task_class','simple_multi_brick_stack','--num_samples','1',
                             '--num_blocks','2','--output_dir',folder)
            self.assertEqual(result.returncode,0,result.stderr)
            instance=Path(folder)/'simple_multi_brick_stack/simple_multi_brick_stack_001'
            self.assertTrue(verifier.verify_instance_dir(instance)[0])
            for n in (1,6):
                rejected=self.call('generator.py','--task_class','simple_multi_brick_stack','--num_blocks',str(n),'--output_dir',folder)
                self.assertNotEqual(rejected.returncode,0)
                self.assertIn('[2, 5]',rejected.stderr)

    def test_empty_verification_root_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertNotEqual(self.call('verifier.py','--benchmark_root',folder).returncode,0)


if __name__=='__main__':
    unittest.main()
