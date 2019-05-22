"""NOTE: READ DOCUMENTATION BEFORE USAGE.

CLI uploader for AHD.
Usage generally follows two steps: the preparation of an upload form, and subsequently its upload to AHD.

Preparation involves the creation of a torrent and the filling out of the associated information in AHD's upload form,
including mediainfo and screenshots. Basic functionality for automatically detecting some other info
(group, codec, etc.) is provided but not highly recommended. The result of this step is a serialized Python dictionary
representing a completed upload form. Advanced users may inspect and/or edit this form, but such functionality is not
currently provided.

Upon finishing the preparation, the form may be uploaded. Uploading requires a cookies file, as logging in on your
behalf is made difficult by a captcha. The cookies file is expected to be in the standard Netscape format
(as used by wget, curl, etc.)and may be extracted from your browser using various extensions.

Usage:
    ahd_uploader.py (-h | --help)
    ahd_uploader.py upload <input_form> --cookies=<cookie_file>
    ahd_uploader.py prepare <media> <output_form> --imdb=<imdb> --passkey=<passkey>
        [--media-type=<media_type> --type=<type> --group=<group> --codec=<codec>]
        [--user-release --special-edition=<edition_information>]

Options:
  -h --help     Show this screen.

  <input_form>     Path to previously prepared upload_form to upload.
  --cookies=<cookie_file>   Path to file containing cookies in the standard Netscape format, used to log in to AHD.

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

"""

import http.cookiejar
import subprocess
import tempfile
from pathlib import Path
import pickle

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

    if 'AMZN' in Path(path).name:
        arguments['--special-edition'] = 'Amazon'

    if 'Netflix' or '.NF.' in Path(path).name:
        arguments['--special-edition'] = 'Netflix'

    assert arguments['--type'] in types
    assert arguments['--codec'] in codecs
    assert arguments['--media-type'] in media_types


def create_torrent(path, passkey):
    announce_url = "http://moose.awesome-hd.me/{}/announce".format(passkey)
    torrent_path = Path(tempfile.gettempdir()) / ("{}.torrent".format(Path(path).stem))
    if torrent_path.exists():
        torrent_path.unlink()
    subprocess.run(['mktorrent', '-l', '22', '-p', '-a', announce_url, '-o', torrent_path, path],
                   capture_output=True, bufsize=0)
    return torrent_path


def get_mediainfo(path):
    if Path(path).is_dir():
        path = next(Path(path).glob('*/')).as_posix()
    return subprocess.check_output(['mediainfo', path])


def get_release_desc(path, passkey):
    if Path(path).is_dir():
        path = next(Path(path).glob('*/')).as_posix()
    script_output = subprocess.check_output(
        ['/opt/anaconda/bin/python', 'aimguploader.py', '-k', passkey, '-n', '4', path],
        bufsize=0)
    return str(script_output).split('BBCode:\\n\\n')[1].split('Done!')[0]


def create_upload_form(arguments):
    path = arguments['<media>']
    passkey = arguments['--passkey']

    preprocessing(path, arguments)

    form = {'submit': (None, 'true'),
            'file_input': (Path(path.name), open(create_torrent(path, passkey), 'rb').read()),
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
            'release_desc': (None, get_release_desc(path, passkey))}
    if arguments['--group'] == 'UNKNOWN':
        form['unknown_group'] = (None, 'on')
        form['group'] = (None, '')
    if arguments['--user-release']:
        form['user'] = (None, 'on')
    if arguments['--special-edition']:
        form['remaster'] = (None, 'on')
        form['remaster_title'] = (None, arguments['--special-edition'])
        if arguments['--special-edition'] not in known_editions:
            form['unknown'] = (None, 'on')

    pickle.dump(form, open(arguments['<output_form>'], 'wb'))
    return form


def upload_form(arguments, form):
    cj = http.cookiejar.MozillaCookieJar(arguments['--cookies'])
    cj.load()
    r = requests.post("https://awesome-hd.me/upload.php",
                      cookies=requests.utils.dict_from_cookiejar(cj),
                      files=form)
    if r.status_code == 200:
        return r.url


if __name__ == '__main__':
    arguments = docopt(__doc__, version='CLI AHD Uploader 1.0')
    if arguments['prepare']:
        print(create_upload_form(arguments))
    if arguments['upload']:
        assert Path(arguments['--cookies']).exists() and not Path(arguments['--cookies']).is_dir()
        assert Path(arguments['<input_form>']).exists() and not Path(arguments['<input_form>']).is_dir()
        print(upload_form(arguments, pickle.load(open(arguments['<input_form>'], 'rb'))))
