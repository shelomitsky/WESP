import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import layout
import wallpaper


class WallpaperTest(unittest.TestCase):
    def setUp(self):
        language=patch.dict(os.environ,LANGUAGE='en')
        language.start()
        self.addCleanup(language.stop)
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.config=self.root/'plasma.conf'
        self.cache=self.root/'cache'
        self.cache.mkdir()
        self.runtime=self.root/'runtime'

    def desktop(self,plugin,values):
        self.config.write_text('[Containments][12]\nplugin=org.kde.plasma.folder\n'
            'lastScreen=0\nactivityId=active\nwallpaperplugin='+plugin+'\n'
            '[Containments][12][Wallpaper]['+plugin+'][General]\n'+values+'\n')

    def test_image_url_and_only_active_plugin_are_used(self):
        image=self.root/'my wallpaper.ppm'
        image.write_bytes(b'P6\n1 1\n255\n\xff\x00\x00')
        self.desktop('org.kde.image','Image='+image.as_uri())
        with self.config.open('a') as handle:
            handle.write('[Containments][12][Wallpaper][old.plugin][General]\nImage=/missing\n')
        path,label=wallpaper.discover(self.config,self.cache,activity='active')
        self.assertEqual(path,image)
        self.assertIn('wallpaper',label.lower())
        self.desktop('org.kde.image','Image=https://example.org/picture.png')
        with self.assertRaises(ValueError):
            wallpaper.discover(self.config,self.cache)

    def test_potd_uses_selected_provider_and_observes_replacement(self):
        self.desktop('org.kde.potd','Provider=bing')
        (self.cache/'flickr').write_bytes(b'unrelated')
        bing=self.cache/'bing:3840:2160'
        bing.write_bytes(b'first')
        (self.cache/'bing:3840:2160.json').write_text('{}')
        self.assertEqual(wallpaper.discover(self.config,self.cache)[0],bing)
        watcher=wallpaper.Watcher(self.config,self.cache,self.runtime)
        with patch.object(wallpaper,'current_activity',return_value=None), \
             patch.object(wallpaper,'sample_pixels',return_value=[(255,0,0,255)]*40):
            watcher.refresh(now=0)
            first=wallpaper.cached(self.runtime)
            # Same image is not decoded on every monitor tick.
            with patch.object(wallpaper,'sample_pixels',side_effect=AssertionError('decoded unchanged image')):
                watcher.refresh(now=3)
        bing.write_bytes(b'new blue image')
        with patch.object(wallpaper,'current_activity',return_value=None), \
             patch.object(wallpaper,'sample_pixels',return_value=[(0,0,255,255)]*40):
            watcher.refresh(now=6)
        second=wallpaper.cached(self.runtime)
        self.assertTrue(first['available'] and second['available'])
        self.assertGreater(first['colors'][0][0],first['colors'][0][2])
        self.assertGreater(second['colors'][0][2],second['colors'][0][0])
        bing.unlink()
        with patch.object(wallpaper,'current_activity',return_value=None):
            watcher.refresh(now=9)
        self.assertFalse(wallpaper.cached(self.runtime)['available'])
        self.assertEqual(wallpaper.cached(self.runtime)['colors'],[list(c) for c in layout.COLORS])

    def test_primary_desktop_of_current_activity_wins_over_panels_and_old_desktops(self):
        self.desktop('org.kde.image','Image=/active.png')
        with self.config.open('a') as handle:
            handle.write('[Containments][99]\nplugin=org.kde.plasma.folder\nlastScreen=0\n'
                'activityId=inactive\nwallpaperplugin=org.kde.image\n'
                '[Containments][99][Wallpaper][org.kde.image][General]\nImage=/inactive.png\n'
                '[Containments][100]\nplugin=org.kde.panel\nlastScreen=0\nwallpaperplugin=org.kde.image\n')
        self.assertEqual(wallpaper.discover(self.config,self.cache,activity='active')[0],Path('/active.png'))

    def test_slideshow_uses_live_slide_instead_of_old_saved_image(self):
        self.desktop('org.kde.slideshow','Image=/old.png\nSlidePaths=/some/folder/')
        def live(screen):
            self.assertEqual(screen,0)
            return dict(wallpaperPlugin='org.kde.slideshow',Image='file:///current%20slide.png')
        with patch.object(wallpaper,'live_wallpaper',side_effect=live):
            path,label=wallpaper.discover(self.config,self.cache,activity='active')
        self.assertEqual(path,Path('/current slide.png'))
        self.assertIn('Slideshow',label)

    def test_live_wallpaper_uses_plasma_read_api_with_unsigned_screen_and_timeout(self):
        test=self
        class UInt32(int):
            pass
        class Object:
            def get_dbus_method(self,name,interface):
                test.assertEqual((name,interface),('wallpaper','org.kde.PlasmaShell'))
                def read(screen,timeout):
                    test.assertIs(type(screen),UInt32)
                    test.assertEqual(screen,2)
                    test.assertGreater(timeout,0)
                    test.assertLessEqual(timeout,1)
                    return dict(wallpaperPlugin='org.kde.slideshow',Image='file:///current.png')
                return read
        class Bus:
            def get_object(self,service,path,introspect):
                test.assertEqual((service,path),('org.kde.plasmashell','/PlasmaShell'))
                test.assertFalse(introspect)
                return Object()
        with patch.dict(sys.modules,dbus=SimpleNamespace(SessionBus=Bus,UInt32=UInt32)):
            self.assertEqual(wallpaper.live_wallpaper(2)['Image'],'file:///current.png')

    def test_slideshow_follows_slide_changes_and_handles_missing_live_image(self):
        self.desktop('org.kde.slideshow','SlidePaths=/some/folder/')
        red,blue=self.root/'red.ppm',self.root/'blue.ppm'
        red.write_bytes(b'P6\n1 1\n255\n\xff\x00\x00')
        blue.write_bytes(b'P6\n1 1\n255\n\x00\x00\xff')
        watcher=wallpaper.Watcher(self.config,self.cache,self.runtime)
        with patch.object(wallpaper,'current_activity',return_value='active'), \
             patch.object(wallpaper,'live_wallpaper',return_value=dict(wallpaperPlugin='org.kde.slideshow',Image=red.as_uri())):
            watcher.refresh(now=0)
        self.assertEqual(wallpaper.cached(self.runtime)['colors'],[[255,0,0]]*10)
        with patch.object(wallpaper,'current_activity',return_value='active'), \
             patch.object(wallpaper,'live_wallpaper',return_value=dict(wallpaperPlugin='org.kde.slideshow',Image=blue.as_uri())):
            watcher.refresh(now=3)
        self.assertEqual(wallpaper.cached(self.runtime)['colors'],[[0,0,255]]*10)
        with patch.object(wallpaper,'current_activity',return_value='active'), \
             patch.object(wallpaper,'live_wallpaper',return_value=dict(wallpaperPlugin='org.kde.slideshow',Image='')):
            watcher.refresh(now=6)
        self.assertFalse(wallpaper.cached(self.runtime)['available'])

    def test_slideshow_does_not_use_stale_image_if_plasma_is_unavailable_or_plugin_changed(self):
        self.desktop('org.kde.slideshow','Image=/old.png')
        with patch.object(wallpaper,'live_wallpaper',side_effect=ValueError('Plasma unavailable')):
            with self.assertRaises(ValueError):
                wallpaper.discover(self.config,self.cache)
        with patch.object(wallpaper,'live_wallpaper',return_value=dict(wallpaperPlugin='org.kde.potd',Image='/old.png')):
            with self.assertRaises(ValueError):
                wallpaper.discover(self.config,self.cache)

    def test_extraction_rejects_transparent_noise_and_preserves_two_main_hues(self):
        pixels=[(220,30,10,255)]*100+[(10,40,230,255)]*80
        pixels += [(0,255,0,0)]*1000+[(0,0,0,255)]*1000
        colors=wallpaper.extract(pixels)
        self.assertEqual(len(colors),10)
        self.assertTrue(any(c[0]>2*c[2] for c in colors))
        self.assertTrue(any(c[2]>2*c[0] for c in colors))
        self.assertFalse(any(c[1]>max(c[0],c[2]) for c in colors))
        self.assertEqual(colors,wallpaper.extract(pixels))
        self.assertTrue(all(0<=v<=255 for c in colors for v in c))

    def test_dark_and_neutral_wallpapers_are_visible_without_inventing_a_hue(self):
        for value in (0,40,200):
            colors=wallpaper.extract([(value,value,value,255)]*40)
            self.assertTrue(all(c[0]==c[1]==c[2] and c[0]>=64 for c in colors))

    def test_bad_cache_is_safe_and_custom_colors_obey_the_meter(self):
        self.runtime.mkdir()
        (self.runtime/'wallpaper-palette.json').write_text('{"available":true,"colors":[[999,0,0]]}')
        self.assertFalse(wallpaper.cached(self.runtime)['available'])
        colors=wallpaper.extract([(255,0,0,255)]*40)
        sections=layout.legacy(20,True,False)
        frame=layout.meter(.5,sections,20,palette='wallpaper',colors=colors)
        self.assertEqual(frame[:10][::-1],frame[10:])
        self.assertEqual(frame[:5],[[0,0,0]]*5)
        self.assertTrue(all(p[0]>0 and p[1]==p[2]==0 for p in frame[5:10]))

    def test_real_image_decoder_and_oversized_header_guard(self):
        image=self.root/'colors.ppm'
        image.write_bytes(b'P6\n2 1\n255\n\xff\x00\x00\x00\x00\xff')
        self.assertEqual(wallpaper.sample_pixels(image),[(255,0,0,255),(0,0,255,255)])
        image.write_bytes(b'P6\n9000 9000\n255\n')
        with self.assertRaises(ValueError):
            wallpaper.sample_pixels(image)


if __name__=='__main__':
    unittest.main()
