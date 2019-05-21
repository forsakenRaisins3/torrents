"""Uploads media as torrent to AHD

Usage:
    ahd_uploader.py (-h | --help)
    ahd_uploader.py <path> --imdb=<imdb> --cookies=<cookie_file> --passkey=<passkey>
        [--media_type=<media_type> --type=<type> --group=<group> --codec=<codec>]
        [--user_release --special_edition=<edition_information>]

Options:
  -h --help     Show this screen.

  <path>    Path to file or directory to create a torrent out of.
  --imdb=<imdb>    IMDb ID, not the full link. Example IMDb ID: tt0113243.
  --cookies=<cookie_file>   Path to text file containing cookies used to log in to AHD.
  --passkey=<passkey>   Your AHD passkey (which is the same as your AIMG API key).

  --type=<type>  Type of content, must be one of Movies, TV-Shows [default: Movies].
  --media_type=<media_type>  Type of media source, must be one of
                             Blu-ray, HD-DVD, HDTV, WEB-DL, WEBRip, DTheater, XDCAM, UHD Blu-ray
                            [default: AUTO-DETECT].
  --codec=<codec>   Codec, must be one of
                    x264, VC-1 Remux, h.264 Remux, MPEG2 Remux, h.265 Remux, x265 [default: AUTO-DETECT].
  --group=<group>   Release group. Specify UNKNOWN for unknown group [default: AUTO-DETECT].

  --user_release    Indicates a user release.
  --special_edition=<edition_information>   If there is any edition information, this is the name of the edition.

"""

import http.cookiejar
import subprocess
import tempfile
from pathlib import Path

import requests
from docopt import docopt

known_editions = ["Director's Cut", "Unrated", "Extended Edition", "2 in 1", "The Criterion Collection"]
types = ['Movies', 'TV-Shows']
media_types = ['Blu-ray', 'HD-DVD', 'HDTV', 'WEB-DL', 'WEBRip', 'DTheater', 'XDCAM', 'UHD Blu-ray']
codecs = ['x264', 'VC-1 Remux', 'h.264 Remux', 'MPEG2 Remux', 'h.265 Remux', 'x265']


def preprocessing(path, arguments):
    assert Path(path).exists()
    assert Path(arguments['--cookies']).exists() and not Path(arguments['--cookies']).is_dir()
    assert arguments['--type'] in types

    if arguments['--codec'] == 'AUTO-DETECT':
        arguments['--codec'] = autodetect_codec(path)
    assert arguments['--codec'] in codecs

    if arguments['--group'] == 'AUTO-DETECT':
        arguments['--group'] = autodetect_group(path)

    if arguments['--media_type'] == 'AUTO-DETECT':
        arguments['--media_type'] = autodetect_media_type(path)
    assert arguments['--media_type'] in media_types


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
    raise RuntimeError("Unable to detect codec")


def autodetect_group(path):
    if Path(path).is_dir():
        path = next(Path(path).glob('*/')).as_posix()
    return '-'.join(Path(path).stem.split('-')[1:])


def create_upload_form(arguments):
    path = arguments['<path>']
    passkey = arguments['--passkey']

    preprocessing(path, arguments)

    form = {'submit': (None, 'true'),
            'file_input': open(create_torrent(path, passkey), 'rb'),
            'nfo_input': (None, ""),
            'type': (None, arguments['--type']),
            'imdblink': (None, arguments['--imdb']),
            'file_media': (None, ""),
            'pastelog': (None, get_mediainfo(path)),
            'group': (None, arguments['--group']),
            'remaster_title': (None, "Director's Cut"),
            'othereditions': (None, ""),
            'media': (None, arguments['--media_type']),
            'encoder': (None, arguments['--codec']),
            'release_desc': (None, get_release_desc(path, passkey))}
    if arguments['--group'] == 'UNKNOWN':
        form['unknown_group'] = (None, 'on')
        form['group'] = (None, '')
    if arguments['--user_release']:
        form['user'] = (None, 'on')
    if arguments['--special_edition']:
        form['remaster'] = (None, 'on')
        form['remaster_title'] = (None, arguments['--special_edition'])
        if arguments['--special_edition'] not in known_editions:
            form['unknown'] = (None, 'on')

    return form


def upload_form(arguments, form):
    cj = http.cookiejar.MozillaCookieJar(arguments['--cookies'])
    cj.load()
    r = requests.post("https://awesome-hd.me/upload.php",
                      cookies=requests.utils.dict_from_cookiejar(cj),
                      # proxies={"http": "http://127.0.0.1:8888", "https": "http://127.0.0.1:8888"},
                      # verify=False,
                      files=form)
    if r.status_code == 200:
        return r.url


if __name__ == '__main__':
    arguments = docopt(__doc__, version='AHD uploader 0.1')
    print(create_upload_form(arguments))
