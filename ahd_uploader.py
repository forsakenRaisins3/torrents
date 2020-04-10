#! /usr/bin/env python3

"""NOTE: READ DOCUMENTATION BEFORE USAGE.

CLI uploader for AHD.
Usage generally follows two steps: the preparation of an upload form, and subsequently its upload to AHD.

Preparation involves the creation of a torrent and the filling out of the associated information in AHD's upload form,
including mediainfo and screenshots. Basic functionality for automatically detecting some other info
(group, codec, etc.) is provided but not recommended. The result of this step is a serialized Python dictionary
representing a completed upload form.
You may also examine the prepared form before uploading using this tool.
Advanced users could edit this form in Python, but such functionality is not currently provided.

Upon finishing the preparation, the form may be uploaded. Uploading currently requires a cookies file, as logging in on
your behalf is made difficult by a captcha. The cookies file is expected to be in the standard Netscape format
(as used by wget, curl, etc.) and may be extracted from your browser using various extensions.
If uploading is successful, the command should output a direct link to the torrent file from AHD; if that doesn't work,
it will output a URL to the media page.

The author of this script is not a member of staff and provides no guarantee that usage of the script will not lead
to violation of site rules either directly or indirectly.

Usage:
    ahd_uploader.py (-h | --help)
    ahd_uploader.py prepare <media> <output_form> --passkey=<passkey>
        [--imdb=<imdb> --media-type=<media_type> --type=<type> --group=<group> --codec=<codec>]
        [--user-release --special-edition=<edition_information>]
        [--num-screens=<num_screens>]
        [--overwrite-existing-torrent]
    ahd_uploader.py examine <input_form>
    ahd_uploader.py upload <input_form> --cookies=<cookie_file> [--delete-on-success]

Options:
  -h --help     Show this screen.


  <media>    Path to file or directory to create a torrent out of.
  <output_form>    Path to save the resulting serialized upload form, which may then be uploaded.
  --passkey=<passkey>   Your AHD passkey (which is the same as your AIMG API key).

  --imdb=<imdb>    IMDb ID, not the full link, e.g tt0113243 [default: AUTO-DETECT].
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
  --overwrite-existing-torrent  By default, if a torrent exists in the expected path, it is used. Use to overwrite.


  <input_form>     Path to previously prepared upload form to examine or upload.
  --cookies=<cookie_file>   Path to file containing cookies in the standard Netscape format, used to log in to AHD.
  --delete-on-success   If set, will try to delete the form file if uploading is succcessful.

"""

import http.cookiejar
import pickle
import shutil
import subprocess
import tempfile
from pathlib import Path
from pprint import pprint

import pendulum
import requests
from docopt import docopt
from guessit import guessit
from imdb import IMDb
from requests_html import HTML
import os

KNOWN_EDITIONS = ["Director's Cut", "Unrated", "Extended Edition", "2 in 1", "The Criterion Collection"]
TYPES = ['Movies', 'TV-Shows']
MEDIA_TYPES = ['Blu-ray', 'HD-DVD', 'HDTV', 'WEB-DL', 'WEBRip', 'DTheater', 'XDCAM', 'UHD Blu-ray']
CODECS = ['x264', 'VC-1 Remux', 'h.264 Remux', 'MPEG2 Remux', 'h.265 Remux', 'x265']


def get_imdb_info(guessit_info):
    g = guessit_info
    q = g['title']
    if 'year' in g:
        q = "{} {}".format(q, g['year'])
    results = IMDb().search_movie(q)
    if len(results) == 0:
        raise RuntimeError("Unable to identify IMDb ID, please specify one manually.")
    return IMDb().search_movie(q)[0]


def autodetect_imdb(path, imdb_info):
    name = Path(path).name
    g = guessit(name)
    if not imdb_info:
        imdb_info = get_imdb_info(g)
    return "tt{}".format(imdb_info.movieID), imdb_info


def autodetect_type(path, imdb_info):
    name = Path(path).name
    g = guessit(name)
    if 'season' in g:
        return 'TV-Shows', imdb_info
    if not imdb_info:
        imdb_info = get_imdb_info(g)
    if imdb_info['kind'] == 'tv series':
        return 'TV-Shows', imdb_info
    try:
        html = HTML(html=requests.get("https://www.imdb.com/title/tt{}".format(imdb_info.movieID)).text)
        if 'TV Special' in html.find('.subtext')[0].html:
            return 'TV-Shows', imdb_info
    except:
        pass
    return 'Movies', imdb_info


def autodetect_media_type(path):
    path = Path(path)
    if 'UHD.BluRay' in path.name:
        return 'UHD Blu-ray'
    if 'BluRay' in path.name:
        return 'Blu-ray'
    for m in MEDIA_TYPES:
        if m in path.name:
            return m
    raise RuntimeError("Unable to detect media type")


def autodetect_codec(path):
    name = Path(path).name
    if 'AVC' in name and 'Remux' in name:
        return 'h.264 Remux'
    for c in CODECS:
        if c in name:
            return c
    return ""


def autodetect_group(path):
    g = guessit(Path(path).name)
    if 'release_group' in g:
        return g['release_group']
    return 'UNKNOWN'


def preprocessing(path, arguments):
    assert Path(path).exists()
    imdb_info = None

    if arguments['--imdb'] == 'AUTO-DETECT':
        arguments['--imdb'], imdb_info = autodetect_imdb(path, imdb_info)

    if arguments['--type'] == 'AUTO-DETECT':
        arguments['--type'], imdb_info = autodetect_type(path, imdb_info)

    if arguments['--group'] == 'AUTO-DETECT':
        arguments['--group'] = autodetect_group(path)

    if arguments['--media-type'] == 'AUTO-DETECT':
        arguments['--media-type'] = autodetect_media_type(path)

    if arguments['--codec'] == 'AUTO-DETECT':
        arguments['--codec'] = autodetect_codec(path)
        if arguments['--media-type'] == 'WEB-DL':
            if arguments['--codec'] == 'x264' or 'H.264' in Path(path).name:
                arguments['--codec'] = 'h.264 Remux'
            if arguments['--codec'] == 'x265' or 'H.265' in Path(path).name or 'HEVC' in Path(path).name:
                arguments['--codec'] = 'h.265 Remux'

    if arguments['--type'] == 'Movies':
        if 'AMZN' in Path(path).name:
            arguments['--special-edition'] = 'Amazon'

        if 'Netflix' in Path(path).name or '.NF.' in Path(path).name:
            arguments['--special-edition'] = 'Netflix'

    assert arguments['--type'] in TYPES
    assert arguments['--codec'] in CODECS
    assert arguments['--media-type'] in MEDIA_TYPES

    assert int(arguments['--num-screens'])
    arguments['--num-screens'] = int(arguments['--num-screens'])


def create_torrent(path, overwrite=False):
    torrent_name = Path(path).stem
    if Path(path).is_dir():
        torrent_name = Path(path).name
    torrent_path = Path(tempfile.gettempdir()) / ("{}.torrent".format(torrent_name))
    if torrent_path.exists():
        if not overwrite:
            return torrent_path
        torrent_path.unlink()
    p = subprocess.run(['mktorrent', '-l', '23', '-p', '-o', str(torrent_path), str(path)],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if p.returncode != 0:
        raise RuntimeError("Error creating torrent: {}".format(p.stdout))
    return torrent_path


def get_mediainfo(path):
    if Path(path).is_dir():
        path = next(Path(path).glob('*/'))
    return subprocess.check_output(['mediainfo', path])


def get_duration(file):
    args = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1',
            file]
    p = subprocess.run(args, stdout=subprocess.PIPE)
    if p.returncode == 127:
        raise ValueError('ffprobe is not installed or not in path.')
    if p.returncode != 0:
        raise RuntimeError('Error occurred while running ffprobe.')
    return float(p.stdout.decode('utf-8'))


def take_screenshot(file, offset_secs, output_dir):
    screenshot_path = Path(output_dir) / ("{}_{}.png".format(Path(file).stem, offset_secs))
    ffmpeg_cmd = ['ffmpeg', '-ss', str(offset_secs), '-i', str(file), '-vframes', '1', str(screenshot_path)]
    p = subprocess.run(ffmpeg_cmd,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if p.returncode == 127:
        raise ValueError('ffmpeg is not installed or not in path.')
    if p.returncode != 0:
        raise RuntimeError('Error occurred while running the ffmpeg command: {}'.format(" ".join(ffmpeg_cmd)))
    
    


def take_screenshots(file, num_screens):
    duration = float(int(get_duration(file)))
    output_dir = Path(tempfile.gettempdir()) / ("{}_screens".format(Path(file).name))
    if output_dir.exists():
        shutil.rmtree(output_dir.resolve())
    Path.mkdir(output_dir)
    offsets = [int(1 / (num_screens + 1) * o * duration) for o in range(1, num_screens + 1)]
    [take_screenshot(file, offset, output_dir) for offset in offsets]
    return str(output_dir)


# def upload_screenshots(gallery_title, files, key):
    # data_payload = {'apikey': key, 'galleryid': 'new', 'gallerytitle': gallery_title}
    # files_payload = [('image[]', (Path(f).name, open(f, 'rb'))) for f in files]
    # return requests.post('https://img.awesome-hd.me/api/upload', data=data_payload, files=files_payload)


def get_release_desc(path, passkey, num_screens):
    if Path(path).is_dir():
        path = next(Path(path).glob('*/')).as_posix()
    gallery_title=Path(path).name
    imgtemp=''.join(take_screenshots(path, num_screens))
    release_info_string=""
    data_payload = {'apikey': passkey, 'galleryid': 'new', 'gallerytitle': gallery_title}
    for filename in os.listdir(imgtemp):
        filename=imgtemp+'/'+filename
        files_payload = [('image[]', open(filename, 'rb'))] 
        imagepost=requests.post('https://img.awesome-hd.me/api/upload', data=data_payload, files=files_payload)
        try:
            response_files = imagepost.json()['files']
        except Exception as e:
            raise ValueError("Error uploading screenshots: {}. Upload request text: {}".format(e, imagepost.text)) from None
        bbcode="".join([f['bbcode'] for f in response_files])
        release_info_string=release_info_string+""+str(bbcode)
    return release_info_string
    


def get_torrent_link_from_html(html):
    """Uses somewhat flimsy HTML parsing due to apparent lack of other options.

    Args:
        html (str): string representing html of upload response.

    Returns:
        str: (hopefully) direct link to torrent.

    """

    html = HTML(html=html)
    user_id = html.search('var userid = {};')[0]
    authkey = html.search('var authkey = "{}";')[0]
    passkey = html.search("passkey={}&")[0]
    user_torrents = [t for t in html.find('[id^=torrent_]') if t.search('user.php?id={}"')[0] == user_id]
    user_torrents_ids_and_dates = [(t.attrs['id'].split('_')[1], pendulum.from_format(t.find('span')[0].attrs['title'],
                                                                                      'MMM DD YYYY, HH:mm')) for t in
                                   user_torrents]
    torrent_id, torrent_dt = max(user_torrents_ids_and_dates, key=lambda x: x[1])
    assert (pendulum.now() - torrent_dt).in_minutes() < 2
    return "https://awesome-hd.me/torrents.php?action=download&id={}&authkey={}&torrent_pass={}".format(torrent_id,
                                                                                                        authkey,
                                                                                                        passkey)


def create_upload_form(arguments):
    path = arguments['<media>']
    passkey = arguments['--passkey']

    preprocessing(path, arguments)

    torrent_path = create_torrent(path, overwrite=arguments['--overwrite-existing-torrent'])

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
        if arguments['--special-edition'] not in KNOWN_EDITIONS:
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
        try:
            if arguments['--delete-on-success']:
                Path(arguments['<input_form>']).unlink()
        except:
            pass
    else:
        raise RuntimeError("Something went wrong while uploading! It's recommended to check AHD to verify that you"
                           "haven't uploaded a malformed or incorrect torrent.")
    try:
        return get_torrent_link_from_html(r.text)
    except:
        return r.url


def upload_form(arguments, form):
    cj = http.cookiejar.MozillaCookieJar(arguments['--cookies'])
    cj.load()
    return requests.post("https://awesome-hd.me/upload.php",
                         cookies=requests.utils.dict_from_cookiejar(cj),
                         files=form)


def examine_form(form):
    form = {k: v[1] for k, v in form.items()}
    form['file_input'] = "<torrent_content>"
    return form


if __name__ == '__main__':
    arguments = docopt(__doc__, version='CLI AHD Uploader 1.2')
    if arguments['prepare']:
        create_upload_form(arguments)
    if arguments['upload']:
        print(upload_command(arguments))
    if arguments['examine']:
        with open(arguments['<input_form>'], 'rb') as form:
            pprint(examine_form(pickle.load(form)))
