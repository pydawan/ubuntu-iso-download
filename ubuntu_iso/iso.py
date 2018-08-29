# This file is part of ubuntu-iso. See LICENSE for license infomation.
"""Ubuntu ISO file."""

import hashlib
import logging
import os
import sys
import tempfile

import gnupg
import requests
from tqdm import tqdm

from .key import UbuntuCDSigningKey
from .release import UbuntuReleaseData

logging.getLogger("gnupg").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)


class ISO:
    """Base ISO."""

    def __init__(self, flavor, codename):
        """TODO."""
        self._log = logging.getLogger(__name__)
        self.release = self.get_ubuntu_release(codename)
        self.target = flavor(self.release)

    def hash(self):
        """TODO."""
        hashes = []
        with tempfile.TemporaryDirectory() as dirpath:
            hash_file = self.download_file(self.target.hash_file, dirpath)
            signed_hash_file = self.download_file(
                self.target.hash_file_signed,
                dirpath
            )
            hashes = open(hash_file, 'r').read().split('\n')
            verified = self.verify_gpg_signature(
                hash_file,
                signed_hash_file,
                dirpath
            )

        if not verified:
            self._log.error('Oops: GPG signature verification failed')
            sys.exit(1)

        target_hash = ''
        for entry in hashes:
            if self.target.filename in entry:
                target_hash = entry.split(' ')[0]

        if not target_hash:
            self._log.error('Oops: No ISO hash found')

        return target_hash

    def download(self, expected_hash):
        """Download the ISO, calculate hash, and and verify it.

        If the expected hash does not match the local hash the
        downloaded ISO will be deleted.
        """
        local_iso = self.download_iso(self.target)
        local_hash = self.calc_sha256(local_iso)

        self._log.debug('Verifying SHA256SUM')
        if expected_hash != local_hash:
            self._log.error(
                'Oops: SHA256 mismatch\n'
                'Expected: %s\n'
                'Actual %s', expected_hash, local_hash
            )
            self.remove_file(local_iso)
            sys.exit(1)

        self._log.info('Download complete and successfully verified')

    def calc_sha256(self, filename):
        """Calculate SHA256 of a given filename.

        The files can be large so the SHA is calculated in chucks.

        Returns:
            SHA256 digest

        """
        self._log.debug('Computing SHA256SUM')

        sha256 = hashlib.sha256()
        with open(filename, 'rb') as file:
            while True:
                data = file.read(65536)
                if not data:
                    break
                sha256.update(data)

        return sha256.hexdigest()

    def download_file(self, file_url, destination_dir):
        """Download a file to specified directory.

        Args:
            file_url: string, URL of file to download
            destination_dir: string, local path to destination
        Returns:
            string, local path to file

        """
        filename = file_url.split('/')[-1]
        destination = os.path.join(destination_dir, filename)

        self._log.debug('Downloading %s', filename)
        with open(destination, 'wb') as f:
            f.write(requests.get(file_url).content)

        return destination

    def download_iso(self, iso):
        """Download the ISO with progress bar.

        This uses tqdm to create a progress bar to show the status of
        the download, total time, remaining time, speed, and overall
        percentage done.

        Args:
            iso: ISO URL object

        Returns:
            string, ISO filename

        """
        self._log.info('Downloading %s', iso.filename)
        response = requests.get(iso.url, stream=True)
        chunk_size = 1024 * 1024

        progress = tqdm(
            total=int(response.headers['Content-Length']),
            unit='B',
            unit_scale=True
        )

        with open(iso.filename, 'wb') as file:
            for chunk in response.iter_content(chunk_size=chunk_size):
                progress.update(len(chunk))
                file.write(chunk)

        progress.close()

        return iso.filename

    def get_ubuntu_release(self, codename=None):
        """Return specified Ubuntu release or latest LTS.

        This will return the release that aligns with the given codename.
        If no codename is provided, then the latest released LTS is
        returned instead.

        Args:
            codename: string, name of Ubuntu release
        Returns:
            UbuntuRelease object

        """
        ubuntu = UbuntuReleaseData()

        if not codename:
            return ubuntu.lts

        release = ubuntu.by_codename(codename)
        if not release.is_supported:
            self._log.error(
                'Oops: \'%s\' is an unsupported release!'
                ' Please choose from:\n%s',
                release.codename,
                [release.codename for release in ubuntu.supported]
            )
            sys.exit(1)

        return release

    @staticmethod
    def remove_file(filename):
        """Remove the given file.

        Args:
            filename: string, path to file
        """
        try:
            os.remove(filename)
        except OSError:
            pass

    def verify_gpg_signature(self, file, signed_file, directory):
        """Verify GPG signature of a signed file.

        This will setup a new GPG key entry at the directory given to
        prevent needing to add the key to the user's keyring. The
        Ubuntu ISO CD singing key will get imported to the keyring.
        Finally, the signed file's signature will be verified with the
        unsigned file.

        The signing key is 0xD94AA3F0EFE21092

        Args:
            file: string, file to verify
            signed_file: string, path to signed file
            directory: string, directory to setup GPG keys

        Return:
            boolean, if verification succeeds

        """
        self._log.debug('Verifying GPG signature')
        gpg = gnupg.GPG(gnupghome=directory)
        gpg.import_keys(UbuntuCDSigningKey)
        if not gpg.verify_file(open(signed_file, 'rb'), file):
            return False

        return True
