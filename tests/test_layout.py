import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import layout


class LayoutTest(unittest.TestCase):
    def test_palettes_keep_meter_level_orientation_and_gaps(self):
        sections=layout.legacy(20,True,False)
        self.assertEqual(layout.meter(1,sections,20),
                         layout.meter(1,sections,20,palette='classic'))
        classic=layout.meter(.55,sections,20)
        for palette in ('fire','ocean','violet','rainbow'):
            frame=layout.meter(.55,sections,20,palette=palette)
            self.assertNotEqual(frame,classic)
            self.assertEqual([any(p) for p in frame],[any(p) for p in classic])
            self.assertEqual(frame[:10][::-1],frame[10:])
            self.assertTrue(all(type(c) is int and 0<=c<=255 for p in frame for c in p))
            self.assertEqual(layout.meter(0,sections,20,palette=palette),[[0,0,0]]*20)
        fire=layout.meter(1,sections,20,palette='fire')
        self.assertEqual(fire[9],[255,24,0])
        self.assertEqual(fire[0],[255,230,120])
        sparse=[dict(sections[0],start=2,count=3)]
        self.assertEqual(layout.meter(1,sparse,7,palette='ocean')[:2],[[0,0,0]]*2)
        self.assertEqual(layout.meter(1,sparse,7,palette='ocean')[5:],[[0,0,0]]*2)

    def test_palette_validation_and_solid_color_override(self):
        sections=layout.legacy(3)
        with self.assertRaises(ValueError):
            layout.meter(1,sections,3,palette='missing')
        self.assertEqual(layout.meter(1,sections,3,[1,2,3],palette='fire'),[[1,2,3]]*3)

    def test_unequal_sections_reverse_and_gaps(self):
        sections = [dict(id='left',name='Left',start=0,count=3,reverse=True,placement='left'),
                    dict(id='right',name='Right',start=5,count=5,reverse=False,placement='right')]
        sections = layout.validate(sections,10)
        frame = layout.meter(.5,sections,10)
        self.assertEqual(len(frame),10)
        self.assertEqual(frame[0],[0,0,0])
        self.assertTrue(any(frame[2]))
        self.assertEqual(frame[3:5],[[0,0,0],[0,0,0]])
        self.assertTrue(any(frame[5]))
        self.assertEqual(frame[9],[0,0,0])
        self.assertEqual(layout.marker(sections),2)

    def test_one_and_ten_sections_of_different_lengths(self):
        for counts in ([37],list(range(1,11))):
            sections=[]
            start=0
            for i,count in enumerate(counts):
                sections.append(dict(id=str(i),name=str(i),start=start,count=count,
                                     reverse=False,placement='custom'))
                start+=count
            sections=layout.validate(sections,start)
            self.assertEqual(len(layout.meter(1,sections,start)),start)
            self.assertTrue(all(any(pixel) for pixel in layout.meter(1,sections,start)))

    def test_rejects_overlap_boolean_count_and_out_of_range(self):
        base=dict(id='a',name='A',start=0,count=10,reverse=False,placement='left')
        for sections in ([base,dict(base,id='b',start=5)], [dict(base,count=True)],
                         [dict(base,start=-1)], [dict(base,count=11)], [],
                         [dict(base,reverse='true')]):
            with self.assertRaises(ValueError):
                layout.validate(sections,10)

    def test_migration_keeps_each_legacy_direction(self):
        sections=layout.legacy(20,True,False)
        self.assertTrue(sections[0]['reverse'])
        self.assertFalse(sections[1]['reverse'])
        self.assertEqual([s['count'] for s in sections],[10,10])
