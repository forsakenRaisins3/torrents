"""NOTE: READ DOCUMENTATION BEFORE USAGE.

CLI uploader for AHD.
Usage generally follows two steps: the preparation of an upload form, and subsequently its upload to AHD.

Preparation involves the creation of a torrent and the filling out of the associated information in AHD's upload form,
including mediainfo and screenshots. Basic functionality for automatically detecting some other info
(group, codec, etc.) is provided but not highly recommended. The result of this step is a serialized Python dictionary
representing a completed upload form. Advanced users may inspect and/or edit this form, but such functionality is not
currently provided.

Upon finishing the preparation, the form may be uploaded. Uploading currently requires a cookies file, as logging in on
your behalf is made difficult by a captcha. The cookies file is expected to be in the standard Netscape format
(as used by wget, curl, etc.) and may be extracted from your browser using various extensions.
If uploading is successful, the command returns a URL to the media page.

The author of this script is not a member of staff and provides no guarantee that usage of the script will not lead
to violation of site rules either directly or indirectly.

Usage:
    ahd_uploader.py (-h | --help)
    ahd_uploader.py upload <input_form> --cookies=<cookie_file> --delete-on-success
    ahd_uploader.py prepare <media> <output_form> --imdb=<imdb> --passkey=<passkey>
        [--media-type=<media_type> --type=<type> --group=<group> --codec=<codec>]
        [--user-release --special-edition=<edition_information>]
        [--num-screens=<num_screens>]

Options:
  -h --help     Show this screen.

  <input_form>     Path to previously prepared upload_form to upload.
  --cookies=<cookie_file>   Path to file containing cookies in the standard Netscape format, used to log in to AHD.
  --delete-on-success   If set, will delete the form file if uploading is succcessful.

  <media>    Path to file or directory to create a torrent out of.
  <output_form>    Path to save the resulting serialized upload form, which may then be uploaded.
  --imdb=<imdb>    IMDb ID, not the full link. Example IMDb ID: tt0113243.
  --passkey=<passkey>   Your AHD passkey (which is the same as your AIMG API key).

  --type=<type>  Type of content, must be one of Movies, TV-Shows [default: AUTO-DETECT].
  --media-type=<media_type>  Type of media source, must be one of
                             Blu-ray, HD-DVD, HDTV, WEB-DL, WEBRip, DTheater, XDCAM, UHD Blu-ray
                            [default: AUTO-DETECT].
  --codec=<codec>   Codec, must be one of
                    x264, VC-1 Remux, h.264 Remux, MPEG2 Remux, h.265 Remux, x265 [default: AUTO-DETECT].
  --group=<group>   Release group. Specify UNKNOWN for unknown group [default: AUTO-DETECT].

  --user-release    Indicates a user release.
  --special-edition=<edition_information>   If there is any edition information, this is the name of the edition.
                                            Current AHD recommendation is not to set this for TV-Shows
                                            (https://awesome-hd.me/wiki.php?action=article&id=30).

  --num-screens=<num_screens>   Number of screenshots to upload and include in description [default: 4]

"""

import http.cookiejar
import subprocess
import tempfile
from pathlib import Path
import pickle
import shutil

import requests
from docopt import docopt

known_editions = ["Director's Cut", "Unrated", "Extended Edition", "2 in 1", "The Criterion Collection"]
types = ['Movies', 'TV-Shows']
media_types = ['Blu-ray', 'HD-DVD', 'HDTV', 'WEB-DL', 'WEBRip', 'DTheater', 'XDCAM', 'UHD Blu-ray']
codecs = ['x264', 'VC-1 Remux', 'h.264 Remux', 'MPEG2 Remux', 'h.265 Remux', 'x265']


def autodetect_type(path):
    if '.S0' in Path(path).name:
        return 'TV-Shows'
    return 'Movies'


def autodetect_media_type(path):
    if Path(path).is_dir():
        path = next(Path(path).glob('*/')).as_posix()
    if 'UHD.BluRay' in Path(path).name:
        return 'UHD Blu-ray'
    if 'BluRay' in Path(path).name:
        return 'Blu-ray'
    for m in media_types:
        if m in Path(path).name:
            return m
    raise RuntimeError("Unable to detect media type")


def autodetect_codec(path):
    if Path(path).is_dir():
        path = next(Path(path).glob('*/')).as_posix()
    for c in codecs:
        if c in Path(path).name:
            return c
    return ""


def autodetect_group(path):
    if Path(path).is_dir():
        path = next(Path(path).glob('*/')).as_posix()
    return Path(path).stem.split('-')[-1]


def preprocessing(path, arguments):
    assert Path(path).exists()

    if arguments['--type'] == 'AUTO-DETECT':
        arguments['--type'] = autodetect_type(path)

    if arguments['--group'] == 'AUTO-DETECT':
        arguments['--group'] = autodetect_group(path)

    if arguments['--media-type'] == 'AUTO-DETECT':
        arguments['--media-type'] = autodetect_media_type(path)

    if arguments['--codec'] == 'AUTO-DETECT':
        arguments['--codec'] = autodetect_codec(path)
        if arguments['--media-type'] == 'WEB-DL':
            if arguments['--codec'] == 'x264' or 'H.264' in Path(path).name:
                arguments['--codec'] = 'h.264 Remux'
            if arguments['--codec'] == 'x265' or 'H.265' in Path(path).name:
                arguments['--codec'] = 'h.265 Remux'

    if arguments['--type'] == 'Movies':
        if 'AMZN' in Path(path).name:
            arguments['--special-edition'] = 'Amazon'

        if 'Netflix' or '.NF.' in Path(path).name:
            arguments['--special-edition'] = 'Netflix'

    assert arguments['--type'] in types
    assert arguments['--codec'] in codecs
    assert arguments['--media-type'] in media_types

    assert int(arguments['--num-screens'])
    arguments['--num-screens'] = int(arguments['--num-screens'])


def create_torrent(path, passkey):
    announce_url = "http://moose.awesome-hd.me/{}/announce".format(passkey)
    torrent_name = Path(path).stem
    if Path(path).is_dir():
        torrent_name = Path(path).name
    torrent_path = Path(tempfile.gettempdir()) / ("{}.torrent".format(torrent_name))
    if torrent_path.exists():
        torrent_path.unlink()
    p = subprocess.run(['mktorrent', '-l', '22', '-p', '-a', announce_url, '-o', torrent_path, path],
                       capture_output=True, shell=True, bufsize=0)
    print(p.returncode)
    return torrent_path


def get_mediainfo(path):
    if Path(path).is_dir():
        path = next(Path(path).glob('*/')).as_posix()
    return subprocess.check_output(['mediainfo', path], shell=True)


def get_duration(file):
    args = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1',
            file]
    p = subprocess.run(args, shell=True, stdout=subprocess.PIPE)
    if p.returncode == 127:
        raise ValueError('ffprobe is not installed or not in path.')
    if p.returncode != 0:
        return RuntimeError('Error occurred while running ffprobe.')
    return float(p.stdout.decode('utf-8'))


def take_screenshot(file, offset_secs, output_dir):
    screenshot_path = Path(output_dir) / ("{}_{}.png".format(Path(file).stem, offset_secs))
    p = subprocess.run(['ffmpeg', '-ss', str(offset_secs), '-i', str(file), '-vframes', '1', str(screenshot_path)],
                       shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if p.returncode == 127:
        raise ValueError('ffmpeg is not installed or not in path.')
    if p.returncode != 0:
        return RuntimeError('Error occurred while running ffmpeg.')
    return screenshot_path


def take_screenshots(file, num_screens):
    duration = float(int(get_duration(file)))
    output_dir = Path(tempfile.gettempdir()) / ("{}_screens".format(Path(file).name))
    if output_dir.exists():
        shutil.rmtree(output_dir.resolve())
    Path.mkdir(output_dir)
    offsets = [int(1 / (num_screens + 1) * o * duration) for o in range(1, num_screens + 1)]
    return [take_screenshot(file, offset, output_dir) for offset in offsets]


def upload_screenshots(gallery_title, files, key):
    data_payload = {'apikey': key, 'galleryid': 'new', 'gallerytitle': gallery_title}
    files_payload = [('image[]', (Path(f).name, open(f, 'rb'))) for f in files]
    return requests.post('https://img.awesome-hd.me/api/upload', data=data_payload, files=files_payload).json()


def get_release_desc(path, passkey, num_screens):
    if Path(path).is_dir():
        path = next(Path(path).glob('*/')).as_posix()
    js = upload_screenshots(Path(path).name, take_screenshots(path, num_screens), passkey)
    if 'files' not in js:
        ValueError('Error uploading screenshots.')
    return "".join([f['bbcode'] for f in js['files']])


def create_upload_form(arguments):
    path = arguments['<media>']
    passkey = arguments['--passkey']

    preprocessing(path, arguments)

    torrent_path = create_torrent(path, passkey)

    form = {'submit': (None, 'true'),
            'file_input': (Path(torrent_path).name, open(torrent_path, 'rb').read()),
            'nfo_input': (None, ""),
            'type': (None, arguments['--type']),
            'imdblink': (None, arguments['--imdb']),
            'file_media': (None, ""),
            'pastelog': (None, get_mediainfo(path)),
            'group': (None, arguments['--group']),
            'remaster_title': (None, "Director's Cut"),
            'othereditions': (None, ""),
            'media': (None, arguments['--media-type']),
            'encoder': (None, arguments['--codec']),
            'release_desc': (None, get_release_desc(path, passkey, arguments['--num-screens']))}
    if arguments['--group'] == 'UNKNOWN':
        form['unknown_group'] = (None, 'on')
        form['group'] = (None, '')
    if arguments['--user-release']:
        form['user'] = (None, 'on')
    if arguments['--special-edition']:
        form['remaster'] = (None, 'on')
        if arguments['--special-edition'] not in known_editions:
            form['othereditions'] = (None, arguments['--special-edition'])
            form['unknown'] = (None, 'on')
        else:
            form['remaster_title'] = (None, arguments['--special-edition'])

    pickle.dump(form, open(arguments['<output_form>'], 'wb'))
    return form


def upload_command(arguments):
    assert Path(arguments['--cookies']).exists() and not Path(arguments['--cookies']).is_dir()
    assert Path(arguments['<input_form>']).exists() and not Path(arguments['<input_form>']).is_dir()
    r = upload_form(arguments, pickle.load(open(arguments['<input_form>'], 'rb')))
    if r.status_code == 200:
        if arguments['--delete-upon-success']:
            Path.unlink(arguments['<input_form>'])
    else:
        raise RuntimeError("Something went wrong while uploading! It's recommended to check AHD to verify that you"
                           "haven't uploaded a malformed or incorrect torrent.")
    return r.url


def upload_form(arguments, form):
    cj = http.cookiejar.MozillaCookieJar(arguments['--cookies'])
    cj.load()
    return requests.post("https://awesome-hd.me/upload.php",
                         cookies=requests.utils.dict_from_cookiejar(cj),
                         files=form)


if __name__ == '__main__':
    arguments = docopt(__doc__, version='CLI AHD Uploader 1.0')
    if arguments['prepare']:
        create_upload_form(arguments)
    if arguments['upload']:
        print(upload_command(arguments))
