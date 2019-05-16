#!/usr/bin/env python


from argparse import ArgumentParser
import json
import os
import pypiper
import re
import sys
import urllib
import yaml
import attmap
from ._version import __version__

from refgenconf import select_genome_config, RefGenomeConfiguration

# This establishes the API with the server
refgenie_server_api = {
    "list_available_genomes": "/genomes",
    'list_assets_by_genome': "/genome/{genome}",
    'download_asset': "/asset/{genome}/{asset}",
}


def is_url(url):
    return urllib.parse(url).scheme != ""


class _VersionInHelpParser(ArgumentParser):
    def format_help(self):
        """ Add version information to help text. """
        return "version: {}\n".format(__version__) + \
               super(_VersionInHelpParser, self).format_help()


def build_argparser():
    """
    Builds argument parser.

    :return argparse.ArgumentParser
    """

    banner = "%(prog)s - builds and manages reference genome assemblies"
    additional_description = "\nhttps://refgenie.databio.org"

    parser = _VersionInHelpParser(
            description=banner,
            epilog=additional_description)


    parser.add_argument(
            "-V", "--version",
            action="version",
            version="%(prog)s {v}".format(v=__version__))

    subparsers = parser.add_subparsers(dest="command") 

    def add_subparser(cmd, description):
        return subparsers.add_parser(
            cmd, description=description, help=description)

    subparser_messages = {
        "init": "Initialize a genome configuration.",
        "list": "List available local genomes.",
        "avail": "List available genomes and indexes on server.",
        "pull": "Download indexes.",
        "build": "Build genome indexes",
    }

    parser.add_argument('-c', '--genome-config', dest="genome_config")

    sps = {}
    for cmd, desc in subparser_messages.items():
        sps[cmd] = add_subparser(cmd, desc)

    sps["init"].add_argument('-s', '--genome-server', default="http://localhost")


    sps["build"] = pypiper.add_pypiper_args(sps["build"], groups=None, args=["recover"])

    default_config = os.path.splitext(os.path.basename(sys.argv[0]))[0] + ".yaml"
    # Arguments to optimize the interface to looper

    # Add any pipeline-specific arguments
    sps["build"].add_argument('-i', '--input', dest='input', required = True,
        help='Local path or URL to genome sequence file in .fa, .fa.gz, or .2bit format.')

    sps["build"].add_argument('-n', '--name', dest='name', required = False,
        help='Name of the genome to build. If omitted, refgenie will use'
        'the basename of the file specified in --input')

    sps["build"].add_argument('-a', '--annotation', dest='annotation', required = False,
        help='Path to GTF gene annotation file')

    sps["build"].add_argument("-d", "--docker", action="store_true",
        help="Run all commands in the refgenie docker container.")

    sps["build"].add_argument('-o', '--outfolder', dest='outfolder', required = False,
        default=None,
        help='Override the default path to genomes folder, which is to '
        'use the genome_folder attribute in the genome configuration file')

    sps["pull"].add_argument('-g', '--genome', default="hg38")
    sps["pull"].add_argument('-a', '--asset', default="bowtie2", nargs='+')

    return parser


def copy_or_download_file(input_string, outfolder):
    """
    Given an input file, which can be a local file or a URL, and output folder, 
    this downloads or copies the file into the output folder.
    @param input_string: Can be either a URL or a path to a local file
    @type input_string: str
    @param outfolder: Where to store the result.
    """
    result_file = os.path.join(outfolder, os.path.basename(input_string))

    if is_url(input_string):
        cmd = "wget -O " + result_file + " " + input_string
    else:
        cmd = "cp " + input_string + " " + result_file
    return([result_file, cmd])

def convert_file(input_file, output_file, conversions):
    """
    Given an input file, output file, and a list of conversions, gives the appropriate output file.
    @param output_file: Path to local output file you want to create
    @param conversions: A dictionary of shell commands to convert files of a given type.
    @type conversions: dict
    """
    form = {"INPUT": input_file, "OUTPUT": output_file}
    ext = os.path.splitext(input_file)[1]
    if ext in conversions:
        cmd = conversions[ext].format(**form)
        return(cmd)
    else:
        # No conversion available/necessary.
        return None


def default_config_file():
    """
    Path to default compute environment settings file.
    
    :return str: Path to default compute settings file
    """
    return os.path.join(os.path.dirname(__file__), "refgenie.yaml")


def build_indexes(args):

    if args.name:
        genome_name = args.name
    else:
        genome_name = os.path.basename(args.input)
        # eliminate extensions to get canonical genome name.
        for strike in [".fasta.gz$", ".fa.gz$", ".fasta$", ".fa$", ".gz$", ".2bit$"]:
            genome_name = re.sub(strike, "", genome_name)

    print("Using genome name: {}".format(genome_name))
    outfolder = os.path.join(args.outfolder, genome_name)
    outfolder = os.path.abspath(outfolder)
    print("Output to: " , genome_name, args.outfolder, outfolder)

    print(default_config_file())

    config_file = args.config_file
    import logging
    if config_file:
        if os.path.isfile(config_file):
            #looks good!
            pass
        else:
            logging.debug("Config file path isn't a file: {}".
                          format(config_file))
            args.config_file = default_config_file()

    pm = pypiper.PipelineManager(name="refgenie", outfolder=outfolder, args=args)
    ngstk = pypiper.NGSTk(pm = pm)
    tools = pm.config.tools  # Convenience alias
    index = pm.config.index
    param = pm.config.param

    #pm.make_sure_path_exists(outfolder)
    conversions = {}
    conversions[".2bit"] = "twoBitToFa {INPUT} {OUTPUT}"
    conversions[".gz"] = ngstk.ziptool + " -cd {INPUT} > {OUTPUT}"

    # Copy fasta file to genome folder structure
    local_raw_fasta = genome_name + ".fa"
    raw_fasta = os.path.join(outfolder, local_raw_fasta)

    input_file = os.path.join(outfolder, os.path.basename(args.input))

    input_file, cmd = copy_or_download_file(args.input, outfolder)
    pm.run(cmd, input_file)

    container = None
    if args.docker:
        # Set up some docker stuff
        pm.get_container("nsheff/refgenie", outfolder)
        # of = os.path.abspath(outfolder)
        # outfolder = of
        # cmd = "docker run -itd"
        # cmd += " -v " + of + ":" + of
        # cmd += " nsheff/refgenie"
        # container = pm.checkprint(cmd).rstrip()
        # print("Using docker container: " + container)
        # pm.atexit_register(remove_container, container)

    cmd = convert_file(input_file, raw_fasta, conversions)
    if cmd:
        pm.run(cmd, raw_fasta, container=pm.container)

    cmd = tools.samtools + " faidx " + raw_fasta
    pm.run(cmd, raw_fasta + ".fai", container=pm.container)

    # Determine chromosome sizes
    fai_file = raw_fasta + ".fai"
    # symlinks should be relative so folders are portable.
    loc_chrom_sizes_file = genome_name + ".chrom.sizes"
    chrom_sizes_file = os.path.join(outfolder, loc_chrom_sizes_file)
    chrom_sizes_alias = os.path.join(outfolder, genome_name + ".chromSizes")
    cmd = "cut -f 1,2 " + fai_file + " > " + chrom_sizes_file
    cmd2 = "ln -s " + loc_chrom_sizes_file + " " + chrom_sizes_alias
    pm.run([cmd, cmd2], chrom_sizes_alias, container=pm.container)

    # Copy annotation file (if any) to folder structure
    if args.annotation:
        annotation_file_unzipped = os.path.join(outfolder, genome_name + ".gtf")
        annotation_file, cmd = copy_or_download_file(args.annotation, outfolder)
        pm.run(cmd, annotation_file)

        cmd = convert_file(annotation_file, annotation_file_unzipped, conversions)
        pm.run(cmd, annotation_file_unzipped)

    #   cmd = "cp " + args.annotation + " " + annotation_file
    #   cmd2 = ngstk.ziptool + " -d " + annotation_file 
    #   pm.run([cmd, cmd2], annotation_file_unzipped)

    else:
        print("* No GTF gene annotations provided. Skipping this step.")


    # Bowtie indexes
    if index.bowtie2:
        folder = os.path.join(outfolder, "indexed_bowtie2")
        ngstk.make_dir(folder)
        target = os.path.join(folder, "completed.flag")
        cmd1 = "ln -sf ../" + local_raw_fasta + " " + folder
        cmd2 = tools.bowtie2build + " " + raw_fasta + " " + os.path.join(folder, genome_name)
        cmd3 = "touch " + target
        pm.run([cmd1, cmd2, cmd3], target, container=pm.container)

    # Bismark index - bowtie2
    if index.bismark_bt2:
        folder = os.path.join(outfolder, "indexed_bismark_bt2")
        ngstk.make_dir(folder)
        target = os.path.join(folder, "completed.flag")
        cmd1 = "ln -sf ../" + local_raw_fasta + " " + folder
        cmd2 = tools.bismark_genome_preparation + " --bowtie2 " + folder
        cmd3 = "touch " + target
        pm.run([cmd1, cmd2, cmd3], target, container=pm.container)

    # Bismark index - bowtie1
    if index.bismark_bt1:
        folder = os.path.join(outfolder, "indexed_bismark_bt1")
        ngstk.make_dir(folder)
        target = os.path.join(folder, "completed.flag")
        cmd1 = "ln -sf ../" + local_raw_fasta + " " + folder
        cmd2 = tools.bismark_genome_preparation + " " + folder
        cmd3 = "touch " + target
        pm.run([cmd1, cmd2, cmd3], target, container=pm.container)

    # Epilog meth calling
    if index.epilog:
        folder = os.path.join(outfolder, "indexed_epilog")
        ngstk.make_dir(folder)
        target = os.path.join(folder, "completed.flag")
        cmd1 = "ln -sf ../" + local_raw_fasta + " " + folder
        cmd2 = tools.epilog_indexer + " -i " + raw_fasta
        cmd2 += " -o " + os.path.join(folder, genome_name + "_" + param.epilog.context + ".tsv")
        cmd2 += " -s " + param.epilog.context  #context
        cmd2 += " -t"
        cmd3 = "touch " + target
        pm.run([cmd1, cmd2, cmd3], target, container=pm.container)

    if index.hisat2:
        folder = os.path.join(outfolder, "indexed_hisat2")
        ngstk.make_dir(folder)
        target = os.path.join(folder, "completed.flag")
        cmd1 = "ln -sf ../" + local_raw_fasta + " " + folder
        cmd2 = tools.hisat2build + " " + raw_fasta + " " + os.path.join(folder, genome_name)
        cmd3 = "touch " + target
        pm.run([cmd1, cmd2, cmd3], target, container=pm.container)

    # Kallisto should index transcriptome
    # So it doesn't make sense to run these at the same time as the others.
    if index.kallisto:
        folder = os.path.join(outfolder, "indexed_kallisto")
        ngstk.make_dir(folder)
        target = os.path.join(folder, "completed.flag")
        cmd2 = tools.kallisto + " index -i " + os.path.join(folder, genome_name + "_kallisto_index.idx")
        cmd2 += " " + raw_fasta
        cmd3 = "touch " + target
        pm.run([cmd2, cmd3], target, container=pm.container)

    pm.stop_pipeline()


def pull_index(rgc, genome, assets, genome_config_path):

    import urllib.request
    import shutil

    print("Pulling assets '{}' from genome '{}'".format(", ".join(assets), genome))
    if not isinstance(assets, list):
        assets = [assets]

    for asset in assets:
        try:
            url = "{base}/asset/{genome}/{asset}".format(base=rgc.to_dict()["genome_server"], genome=genome, asset=asset)

            # local file to save as
            file_name = "{genome_folder}/{genome}/{asset}.tar".format(
                genome_folder=rgc.genome_folder,
                genome=genome,
                asset=asset)

            # Download the file from `url` and save it locally under `file_name`:
            print("Downloading URL: {}".format(url))

            if not os.path.exists(os.path.dirname(file_name)):
                print("Directory {} does not exist, creating it...".format(os.path.dirname(file_name)))
                os.mkdir(os.path.dirname(file_name))

            with urllib.request.urlopen(url) as response:

                with open(file_name, 'wb') as out_file:
                    shutil.copyfileobj(response, out_file)
            print("Download complete: {}".format(file_name))

            # successfully downloaded and moved tarball; untar it
            # TODO: Make this a CLI option
            unpack = True

            if unpack:

                if file_name.endswith(".tar"):
                    import tarfile
                    with tarfile.open(file_name) as tf:
                        x = tf.extractall(path=os.path.dirname(file_name))
                        print(x)

                if file_name.endswith(".tgz"):
                    import tarfile
                    with tarfile.open(file_name) as tf:
                        tf.extractall(path=os.path.dirname(file_name))

                print("Unpackaged archive into: {}".format(os.path.dirname(file_name)))

                # Write to config file
                # TODO: Figure out how we want to handle the asset_key to folder_name
                # mapping. Do we want to require that asset_key == folder_name?
                # I guess we allow it to differ, but we keep it that way within refgenie?
                # Right now they are identical:
                asset_key = asset
                folder_name = asset
                print("Writing genome config file: {}".format(genome_config_path))
                rgc.genomes[genome][asset_key] = folder_name
                rgc.write(genome_config_path)

        except urllib.error.HTTPError as e:
            print(e)
            print("File not found on server")
        except ConnectionRefusedError as e:
            print(e)
            print("Server {} refused download. Check your internet settings".format(rgc.to_dict()["genome_server"]))
            pass
        except FileNotFoundError as e:
            print(e)
            print("Local genomes folder '{}' not found.".format(rgc.genome_folder))
            pass

def avail(rgc):
    """ What's available? """

    url = "{base}/assets".format(base=rgc.to_dict()["genome_server"])
    print("Querying available assets from server: {url}".format(url=url))
    with urllib.request.urlopen(url) as response:
        encoding = response.info().get_content_charset('utf8')
        data = json.loads(response.read().decode(encoding))
        avail_rgc = attmap.AttMap(data)
        print(avail_rgc.to_yaml())


def refgenie_init(genome_config_path, genome_server="http://localhost"):
    """ Initialize genome config """

    # Set up default 
    rgc = RefGenomeConfiguration({})
    rgc.genome_folder = os.path.dirname(genome_config_path)
    rgc.genome_server = genome_server
    rgc.genomes = None

    print(rgc)

    if genome_config_path and not os.path.exists(genome_config_path):
        rgc.write(genome_config_path)
        print("Wrote new refgenie genome configuration file: {}".format(genome_config_path))
    else:
        print("Can't initialize, file exists: {} ".format(genome_config_path))



def main():
    """ Primary workflow """


    parser = build_argparser()
    args, remaining_args = parser.parse_known_args()

    print(args)

    if not args.command:
        parser.print_help()
        print("No command given")
        sys.exit(1)


    if args.command == "init":
        print("Initializing refgenie genome configuration")
        refgenie_init(args.genome_config, args.genome_server)
        sys.exit(0)

    
    genome_config_path = select_genome_config(args.genome_config)
    rgc = RefGenomeConfiguration(genome_config_path)

    if not rgc:
        parser.print_help()
        print("Can't load genome configuration file")
        sys.exit(1)

    if args.command == "build":
        build_indexes(args)

    if args.command == "list":
        print("Local genomes: {}".format(rgc.genomes_str()))
        print("Local assets:\n{}".format(rgc.assets_str()))

    if args.command == "pull":
        pull_index(rgc, args.genome, args.asset, genome_config_path)

    if args.command == "avail":
        avail(rgc)

if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("Program canceled by user!")
        sys.exit(1)


