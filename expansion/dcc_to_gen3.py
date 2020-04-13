"""
This script can be used to convert a file download manifest from https://dcc.icgc.org/
to a manifest that the gen3-client (https://github.com/uc-cdis/cdis-data-client) can use.

Examples:
python dcc_to_gen3.py -m dcc_manifest.sh
python dcc_to_gen3.py -m dcc_manifest.sh -i icgc.bionimbus.org_indexd_records.txt

Arguments:
    - manifest(str, required): The manifest downloaded from the DCC portal,e.g., "/Users/christopher/Documents/Notes/ICGC/dcc_manifest.pdc.1581529402015.sh".
    - indexd(str, not required): If a file already exists with the data commons indexd records, provide the path to that file. Otherwise, if not provided, the indexd database will be queried until it collects all file records.

Use the generated manifest with the gen3-client, downloaded here: https://github.com/uc-cdis/cdis-data-client/releases/latest

Gen3-Client Example:
    gen3-client configure --profile=icgc --apiendpoint=https://icgc.bionimbus.org/ --cred=~/Downloads/icgc-credentials.json
    gen3-client download-multiple --profile=icgc --manifest=gen3_manifest_dcc_manifest.sh.json --no-prompt --download-path='icgc_pcawg_files'

"""
import json, requests, os, argparse, re
import pandas as pd

global locs, irecs, args, token, all_records

def parse_args():
    parser = argparse.ArgumentParser(description="Generate a gen3-client manifest from a DCC manifest by retrieving GUIDs for files from indexd.")
    parser.add_argument("-m", "--manifest", required=True, help="The manifest downloaded from DCC portal.",default="dcc_manifest.pdc.1581529402015.sh")
    parser.add_argument("-a", "--api", required=False, help="The data commons URL.",default="https://icgc.bionimbus.org/")
    parser.add_argument("-i", "--indexd", required=False, help="If a file already exists with the data commons indexd records, provide the path to that file.",default=False) # default="icgc.bionimbus.org_indexd_records.txt"
    args = parser.parse_args()
    return args


def query_indexd(api,limit=100,page=0):
    """ Queries indexd with given records limit and page number.
        For example:
            records = query_indexd(api='https://icgc.bionimbus.org/',limit=1000,page=0)
            https://icgc.bionimbus.org/index/index/?limit=1000&page=0
    """
    data,records = {},[]
    index_url = "{}/index/index/?limit={}&page={}".format(api,limit,page)

    try:
        response = requests.get(index_url).text
        data = json.loads(response)
    except Exception as e:
        print("\tUnable to parse indexd response as JSON!\n\t\t{} {}".format(type(e),e))

    if 'records' in data:
        records = data['records']
    else:
        print("\tNo records found in data from '{}':\n\t\t{}".format(index_url,data))

    return records

def get_indexd(limit=100,outfile=True,page=0):
    """ get all the records in indexd
        api = "https://icgc.bionimbus.org/"
        args = lambda: None
        setattr(args, 'api', api)
        setattr(args, 'limit', 100)
        i = get_indexd()
    """

    stats_url = "{}/index/_stats".format(args.api)
    try:
        response = requests.get(stats_url).text
        stats = json.loads(response)
        print("Stats for '{}': {}".format(args.api,stats))
    except Exception as e:
        print("\tUnable to parse indexd response as JSON!\n\t\t{} {}".format(type(e),e))

    print("Getting all records in indexd (limit: {}, starting at page: {})".format(args.limit,page))

    all_records = []

    done = False
    while done is False:

        records = query_indexd(api=args.api,limit=args.limit,page=page)
        all_records.extend(records)

        if len(records) != args.limit:
            print("\tLength of returned records ({}) does not equal limit ({}).".format(len(records),args.limit))
            if len(records) == 0:
                done = True

        print("\tPage {}: {} records ({} total)".format(page,len(records),len(all_records)))
        page += 1

    print("\t\tScript finished. Total records retrieved: {}".format(len(all_records)))

    if outfile:
        dc_regex = re.compile(r'https:\/\/(.+)\/')
        dc = dc_regex.match(args.api).groups()[0]
        outname = "{}_indexd_records.txt".format(dc)
        with open(outname, 'w') as output:
            output.write(json.dumps(all_records))

    return all_records


def read_dcc_manifest():

    try:
        with open(args.manifest, 'r') as dcc_file:
            dcc_lines = [line.rstrip() for line in dcc_file]
    except Exception as e:
        print("Couldn't read the manifest file '{}': {} ".format(args.indexd,e))

    dcc_regex = re.compile(r'^.+cp (s3.+) \.$')
    dcc_files = [dcc_regex.match(i).groups()[0] for i in dcc_lines if dcc_regex.match(i)]

    return dcc_files

def write_manifest():
    """ write the gen3-client manifest
    """
    #locs = {irec['urls'][0]: irec for irec in irecs}
    count = 0
    total = len(dcc_files)
    mname = "gen3_manifest_{}.json".format(args.manifest)

    with open(mname, 'w') as manifest:
        manifest.write('[')
        for loc in dcc_files:
            count+=1

            fsize = locs[loc]['size']
            object_id = locs[loc]['did']

            manifest.write('\n\t{')
            manifest.write('"object_id": "{}", '.format(object_id))
            manifest.write('"location": "{}", '.format(loc))
            manifest.write('"size": "{}"'.format(fsize))

            if count == len(dcc_files):
                manifest.write('  }]')
            else:
                manifest.write('  },')

            print("\t{} ({}/{})".format(object_id,count,total))

        print("\tDone ({}/{}).".format(count,total))
        print("\tManifest written to file: {}".format(mname))


if __name__ == "__main__":

    args = parse_args()

    if args.indexd:
        try:
            print("Reading provided indexd file '{}'".format(args.indexd))
            with open(args.indexd, 'r') as indexd_file:
                itxt = indexd_file.readline()
                irecs = json.loads(itxt)
                print("\t{} file records were found in the indexd file.".format(len(irecs)))
        except Exception as e:
            print("Couldn't load the file '{}': {} ".format(args.indexd,e))
    else:
        print("No filename provided for indexd records, fetching file index records from {}.".format(args.api))
        irecs = get_indexd(args.api)
        print("\t{} total records retrieved from {}.".format(len(irecs),args.api))

    locs = {irec['urls'][0]: irec for irec in irecs}

    print("Reading the dcc manifest: {}".format(args.manifest))
    dcc_files = read_dcc_manifest()
    print("\tFound {} files in this dcc manifest.".format(len(dcc_files)))

    print("Writing the gen3-client manifest.")
    write_manifest()














    # # trouble-shooting
    # cred = '/Users/christopher/Downloads/icgc-credentials.json'
    # api = 'https://icgc.bionimbus.org/'
    # with open (cred, 'r') as f:
    #     credentials = json.load(f)
    # token_url = "{}/user/credentials/api/access_token".format(api)
    # resp = requests.post(token_url, json=credentials)
    # if (resp.status_code != 200):
    #     raise(Exception(resp.reason))
    # token = resp.json()['access_token']
    #
    # headers = {'Authorization': 'bearer ' + token}
    # all_records = []
    # indexd_url = "{}/index/index".format(api)
    # response = requests.get(indexd_url, headers=headers) #response = requests.get(indexd_url, auth=auth)
    # records = response.json().get("records")
    #
    # response = requests.get(indexd_url)

# # manifest = 'dcc_manifest.sh'
#         with open(manifest, 'r') as dcc_file:
#             dcc_files = [line.rstrip() for line in dcc_file]
