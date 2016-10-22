import os
import subprocess as sp
import logging
logger = logging.getLogger(__name__)

def upload(package, token=None, label=None):
    """
    Upload a package to anaconda.

    Parameters
    ----------
    package : str
        Filename to built package

    token : str
        If None, use the environment variable ANACONDA_TOKEN, otherwise, use
        this as the token for authenticating the anaconda client.

    label : str
        Optional label to add, see
        https://docs.continuum.io/anaconda-cloud/using#Uploading. Mostly useful
        for testing.
    """
    label_arg = []
    if label is not None:
        label_arg = ['--label', label]

    if not os.path.exists(package):
        logger.error("BIOCONDA UPLOAD ERROR: package %s cannot be found.",
                     package)
        return False

    if token is None:
        token = os.environ.get('ANACONDA_TOKEN')
        if token is None:
            raise ValueError("Env var ANACONDA_TOKEN not found")

    logger.info("BIOCONDA UPLOAD uploading package %s", package)
    try:
        sp.run(
            [
                "anaconda", "-t", token, 'upload', package
            ] + label_arg,
            stdout=sp.PIPE,
            stderr=sp.STDOUT,
            check=True,
            universal_newlines=True
        )

        logger.info("BIOCONDA UPLOAD SUCCESS: uploaded package %s", package)
        return True

    except sp.CalledProcessError as e:
        if "already exists" in e.stdout:
            # ignore error assuming that it is caused by
            # existing package
            logger.warning(
                "BIOCONDA UPLOAD WARNING: tried to upload package, got: "
                "%s", e.stdout)
            return True
        else:
            # to avoid broadcasting the token in logs
            e.args = ['<overwritten>']
            raise e
