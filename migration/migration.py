import os, os.path, sys, subprocess, glob, json, re, operator
from shutil import copyfile
import pandas as pd
import numpy as np
sys.path.insert(1, '/Users/christopher/Documents/GitHub/cgmeyer/gen3sdk-python/expansion')
from expansion import Gen3Expansion

# turn off pandas chained assignment warning
pd.options.mode.chained_assignment = None

def make_temp_files(prefix,suffix,name='temp'):
    """
    Make copies of all files matching a pattern with "temp_" prefix added.
    Args:
        prefix(str): A sub-string at the beginning of file names.
        suffix(str): A sub-string at the end of file names.
        name(str): The sub-string to add at the beginning of copies.
    Example:
        This makes a copy of every TSV file beginning with "DEV" (that is, files matching DEV*tsv) and names the copies temp_DEV*tsv.
        make_temp_files(prefix='DEV',suffix='tsv')
    """
    pattern = "{}*{}".format(prefix,suffix)
    file_names = glob.glob(pattern)
    for file_name in file_names:
        temp_name = "temp_{}".format(file_name)
        copyfile(file_name, temp_name)

def merge_nodes(project_id,in_nodes,out_node):
    """
    Merges a list of node TSVs into a single TSV.
    Args:
        in_nodes(list): List of node TSVs to merge into a single TSV.
        out_node(str): The name of the new merged TSV.
    """
    dfs = []
    for node in in_nodes:
        filename = "temp_{}_{}.tsv".format(project_id, node)
        try:
            df1 = pd.read_csv(filename,sep='\t', header=0, dtype=str)
            dfs.append(df1)
            print("{} node found with {} records.".format(node,len(df1)))
        except IOError as e:
            print("Can't read file {}".format(filename))
            pass
    df = pd.concat(dfs, ignore_index=True)
    df['type'] = out_node
    outname = "temp_{}_{}.tsv".format(project_id, out_node)
    df.to_csv(outname, sep='\t', index=False, encoding='utf-8')
    print("Total of {} records written to node {} in file {}.".format(len(df),out_node,outname))
    return df

def add_missing_links(project_id,node,link):
    """
    This function adds missing links to a node's TSV when the parent node changes.
    Args:
        node (str): This is the node TSV to add links to.
        link (str): This is the name of the node to add links to.
    Example:
        This adds missing links to the visit node to the imaging_exam TSV.
        add_missing_links(node='imaging_exam',link='visit')
    """
    filename = "temp_{}_{}.tsv".format(project_id, node)
    df = pd.read_csv(filename,sep='\t', header=0, dtype=str)
    link_name = "{}s.submitter_id".format(link)
    df_no_link = df.loc[df[link_name].isnull()] # imaging_exams with no visit
    if len(df_no_link) > 0:
        df_no_link[link_name] = df_no_link['submitter_id'] + "_{}".format(link) # visit submitter_id is "<ESID>_visit"
        #df_no_link = df_no_link.drop(columns=['visits.id'])
        # Merge dummy visits back into original df
        df_link = df.loc[df[link_name].notnull()]
        df_final = pd.concat([df_link,df_no_link],ignore_index=True,sort=False)
        df_final.to_csv(filename, sep='\t', index=False, encoding='utf-8')
        print("{} links to node {} added for {} in TSV file: {}".format(str(len(df_no_link)),link,node,filename))
        return df_final
    else:
        print("No records are missing links to {} in the {} TSV.".format(link,node))
        return df

def create_missing_links(project_id,node,link,old_parent,properties):
    """
    This fxn creates links TSV for links in a node that don't exist.

    Args:
        node(str): This is the node TSV in which to look for links that don't exist.
        link(str): This is the node to create the link records in.
        old_parent(str): This is the parent node of 'node' prior to the dictionary change.
        properties(dict): Dict of required properties/values to add to new link records.
    Example:
        This will create visit records that don't exist in the visit TSV but are in the imaging_exam TSV.
        create_missing_links(node='imaging_exam',link='visit',old_parent='case',properties={'visit_label':'Imaging','visit_method':'In-person Visit'})
    """
    filename = "temp_{}_{}.tsv".format(project_id,node)
    df = pd.read_csv(filename,sep='\t',header=0,dtype=str)
    link_name = "{}s.submitter_id".format(link)
    link_names = list(df[link_name])
    link_file = "temp_{}_{}.tsv".format(project_id,link)
    try:
        link_df = pd.read_csv(link_file,sep='\t',header=0,dtype=str)
        existing = list(link_df['submitter_id'])
        missing = set(link_names).difference(existing) #lists items in link_names missing from existing
        if len(missing) > 0:
            print("Creating {} records in {} node for missing {} links.".format(len(missing),link,node))
        else:
            print("All {} records in {} node have existing links to {} in {}. No new records added.".format(len(df),node,link,link_file))
            print("Returning {} records that are {} links.".format(link,node))
            return link_df.loc[link_df['submitter_id'].isin(link_names)]
    except FileNotFoundError as e:
        link_df = pd.DataFrame()
        print("No existing {} TSV found. Creating new TSV for links.".format(link))
        missing = link_names
    parent_link = "{}s.submitter_id".format(old_parent)
    new_links = df.loc[df[link_name].isin(missing)][[link_name,parent_link]]
    new_links = new_links.rename(columns={link_name:'submitter_id'})
    new_links['type'] = link
    for prop in properties:
        new_links[prop] = properties[prop]
    all_links = pd.concat([link_df,new_links],ignore_index=True)
    all_links.to_csv(link_file,sep='\t',index=False,encoding='utf-8')
    print("{} new missing {} records saved into TSV file: {}".format(str(len(new_links)),link,link_file))
    return all_links

def move_properties(project_id,from_node,to_node,properties,parent_node='visit'):
    """
    This function takes a node with properties to be moved (from_node) and moves those properties/data to a new node (to_node).
    Fxn also checks whether the data for proeprties to be moved actually has non-null data. If all data are null, no new records are created.
    Args:
        from_node(str): Node TSV to copy data from.
        to_node(str): Node TSV to add copied data to.
        properties(list): List of column headers containing data to copy.
        parent_node(str): The parent node that links the from_node to the to_node, e.g., 'visit' or 'case'.
    Example:
        This moves the property 'military_status' from 'demographic' node to 'military_history' node, which should link to the same parent node 'case'.
        move_properties(from_node='demographic',to_node='military_history',properties=['military_status'],parent_node='case')
    """
    from_name = "temp_{}_{}.tsv".format(project_id,from_node) #from imaging_exam
    df_from = pd.read_csv(from_name,sep='\t',header=0,dtype=str)
    to_name = "temp_{}_{}.tsv".format(project_id,to_node) #to reproductive_health
    try:
        df_to = pd.read_csv(to_name,sep='\t',header=0,dtype=str)
    except FileNotFoundError as e:
        df_to = pd.DataFrame(columns=['submitter_id'])
        print("No existing {} TSV found. Creating new TSV for data to be moved.".format(to_node))
    parent_link = "{}s.submitter_id".format(parent_node)
    from_no_link = df_from.loc[df_from[parent_link].isnull()] # from_node records with no link to parent_node
    if not from_no_link.empty: # if there are records with no links to parent node
        print("Warning: there are {} {} records with no links to {} node!".format(len(from_no_link),from_node,parent_node))
        print("Returning original data.")
        return df_from
    else:
        proceed = False # only create new records if data to move aren't entirely null
        for prop in properties:
            if len(df_from.loc[df_from[prop].notnull()]) > 0:
                proceed = True
        if proceed:
            # create the reproductive_health nodes based on imaging exams
            all_props = [parent_link] + properties
            new_to = df_from[all_props]
            new_to['type'] = to_node
            new_to['project_id'] = project_id
            new_to['submitter_id'] = df_from['submitter_id'] + "_reproductive_health"
            #only write new_to records if submitter_ids don't already exist in df_to:
            add_to = new_to.loc[~new_to['submitter_id'].isin(list(df_to.submitter_id))]
            all_to = pd.concat([df_to,add_to],ignore_index=True,sort=False)
            all_to.to_csv(to_name,sep='\t',index=False,encoding='utf-8')
            print("{} new {} records created from data moved from {} written to file:\n\t{}".format(len(add_to),to_node,from_node,to_name))
            return all_to
        else:
            print("No non-null {} data found in {} records. No TSVs changed.".format(to_node,from_node))
            print("Returning original {} data.".format(from_node))
            return df_from

def change_property_names(project_id,node,properties):
    """
    Changes the names of columns in a TSV.
    Args:
        node(str): The name of the node TSV to change column names in.
        properties(dict): A dict with keys of old prop names to change with values as new names.
    Example:
        This changes the column header "time_of_surgery" to "hour_of_surgery" in the surgery TSV.
        change_property_names(node='surgery',properties={'time_of_surgery','hour_of_surgery'})
    """
    filename = "temp_{}_{}.tsv".format(project_id,node)
    try:
        df = pd.read_csv(filename,sep='\t',header=0,dtype=str)
        df.rename(columns=properties,inplace = True)
        df.to_csv(filename,sep='\t',index=False,encoding='utf-8')
        print("Properties names changed and TSV written to file: \n\t{}".format(filename))
        return df
    except Exception as e:
        print("Couldn't change property names: {}".format(e))


def drop_properties(project_id,node,properties):
    """
    Function drops the list of properties from column headers of a node TSV.
    Args:
        node(str): The node TSV to drop headers from.
        properties(list): List of column headers to drop from the TSV.
    Example:
        This will drop the 'military_status' property from the 'demographic' node.
        drop_properties(node='demographic',properties=['military_status'])
    """
    filename = "temp_{}_{}.tsv".format(project_id,node)
    df = pd.read_csv(filename,sep='\t',header=0,dtype=str)
    try:
        df = df.drop(columns=properties)
        df.to_csv(filename,sep='\t',index=False,encoding='utf-8')
        print("Properties dropped and TSV written to file: \n\t{}".format(filename))
    except Exception as e:
        print("Couldn't drop properties from {}:\n\t{}".format(node,e))
    return df

def drop_links(project_id,node,links):
    """
    Function drops the list of nodes in 'links' from column headers of a node TSV, including the 'id' and 'submitter_id' for the link.
    Args:
        project_id(str): The project_id of the TSV.
        node(str): The node TSV to drop link headers from.
        links(list): List of node link headers to drop from the TSV.
    Example:
        This will drop the links to 'cases' node from the 'demographic' node.
        drop_links(project_id=project_id,node='demographic',links=['cases'])
    """
    filename = "temp_{}_{}.tsv".format(project_id,node)
    df = pd.read_csv(filename,sep='\t',header=0,dtype=str)
    for link in links:
        sid = "{}.submitter_id".format(link)
        uuid = "{}.id".format(link)
        if sid in df.columns and uuid in df.columns:
            df = df.drop(columns=[sid,uuid])
        else:
            count=1
            sid = "{}.submitter_id#{}".format(link,count)
            uuid = "{}.id#{}".format(link,count)
            while sid in df.columns and uuid in df.columns:
                df.drop(columns=[sid,uuid])
                count+=1
                sid = "{}.submitter_id#{}".format(link,count)
                uuid = "{}.id#{}".format(link,count)
    df.to_csv(filename,sep='\t',index=False,encoding='utf-8')
    print("Links dropped and TSV written to file: \n\t{}".format(filename))
    return df

def merge_links(project_id,node,link,links_to_merge):
    """
    Function merges links in 'links_to_merge' into a single 'link' in a 'node' TSV.
    This would be used on a child node after the merge_nodes function was used on a list of its parent nodes.
    Args:
        project_id(str): The project_id of the TSV.
        link(str): The master link to merge links to.
        links_to_merge(list): List of links to merge into link.
    Example:
        This will merge 'imaging_mri_exams' and 'imaging_fmri_exams' into one 'imaging_exams' column.
        merge_links(project_id=project_id,node='imaging_file',link='imaging_exams',links_to_merge=['imaging_mri_exams','imaging_fmri_exams'])
    """
    # This fxn is mostly for merging the 7 imaging_exam subtypes into one imaging_exams link for imaging_file node. Not sure what other use cases there may be.
    # links_to_merge=['imaging_fmri_exams','imaging_mri_exams','imaging_spect_exams','imaging_ultrasonography_exams','imaging_xray_exams','imaging_ct_exams','imaging_pet_exams']
    filename = "temp_{}_{}.tsv".format(project_id,node)
    df = pd.read_csv(filename,sep='\t',header=0,dtype=str)
    link_name = "{}.submitter_id".format(link)
    df[link_name] = np.nan
    for sublink in links_to_merge:
        sid = "{}.submitter_id".format(sublink)
        df.loc[df[link_name].isnull(), link_name] = df[sid]
        #df[link_name] = df[link_name].fillna(df[sid])
    df.to_csv(filename,sep='\t',index=False,encoding='utf-8')
    print("Links merged to {} and TSV written to file: \n\t{}".format(link,filename))
    return df

def get_submission_order(dd,project_id,prefix='temp',suffix='tsv'):
    pattern = "{}*{}".format(prefix,suffix)
    file_names = glob.glob(pattern)
    all_nodes = []
    suborder = {}
    for file_name in file_names:
        regex = "{}_{}_(.+).{}".format(prefix,project_id,suffix)
        #match = re.search('AAA(.+)ZZZ', text)
        match = re.search(regex, file_name)
        if match:
            node = match.group(1)
            if node in list(dd):
                all_nodes.append(node)
            else:
                print("The node '{}' is not in the data dictionary! Skipping...".format(node))
    while len(all_nodes) > 0:
        node = all_nodes.pop(0)
        #print("Finding order for node {}".format(node))
        node_links = dd[node]['links']
        for link in node_links:
            if 'subgroup' in list(link):
                for sub in link['subgroup']:
                    if sub['target_type'] == 'project':
                        suborder[node]=1
                    elif sub['target_type'] in list(suborder.keys()):
                        suborder[node]=suborder[sub['target_type']]+1
                    elif sub['target_type'] == 'core_metadata_collection':
                        pass
                    else:
                        all_nodes.append(node)
                        #print("Skipping {} for now.".format(node))
            elif 'target_type' in list(link):
                if link['target_type'] == 'project':
                    suborder[node]=1
                elif link['target_type'] in list(suborder.keys()):
                    suborder[node]=suborder[link['target_type']]+1
                else: #skip it for now
                    all_nodes.append(node)
                    #print("Skipping {} for now.".format(node))
            else:
                print("No link target_type found for node '{}'".format(node))
    suborder = sorted(suborder.items(), key=operator.itemgetter(1))
    return suborder