"""Prepara o FFmpeg que será usado pela interface local."""
from pathlib import Path
import shutil
import imageio_ffmpeg

if __name__ == '__main__':
    target = Path(__file__).resolve().parent / 'ffmpeg.exe'
    shutil.copy2(imageio_ffmpeg.get_ffmpeg_exe(), target)
    print(f'FFmpeg preparado: {target}')
