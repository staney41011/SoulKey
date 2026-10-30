"""Do not generate a P259-L04 source_info.json for the wrong YouTube ID."""
import pathlib,sys,unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from p259_source_duration_restore import source_video_id
class Tests(unittest.TestCase):
    def test_exact_registered_lesson_four(self):
        self.assertEqual(source_video_id("https://youtu.be/w7rzYft4MeE"),"w7rzYft4MeE")
        self.assertEqual(source_video_id("https://www.youtube.com/watch?v=w7rzYft4MeE"),"w7rzYft4MeE")
    def test_non_video_or_invalid_url_never_guessed(self):
        self.assertEqual(source_video_id("http://not-video.example"),"")
        self.assertEqual(source_video_id("https://youtu.be/bad"),"")
if __name__=="__main__":unittest.main(verbosity=2)
