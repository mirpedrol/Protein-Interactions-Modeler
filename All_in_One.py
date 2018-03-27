import argparse

def ParsePDB(pdbfiles):
	"""
	Parses PDB files using biopython by creating PDBParser objects.

	Arguments:

	pdbfiles: list of PDB file names to parse.
	"""

	PDB_objects = []
	PDB_names = []

	for file in pdbfiles:
		name = file.split(".")[0]
		pdb = PDBParser(QUIET=True).get_structure(name, file)
		PDB_objects.append(pdb)
		PDB_names.append(name)

	return (PDB_objects, PDB_names)

def SplitChain(PDB_objects):
	"""
	Splits a list of PDB files by chain creating one PDB and one FASTA file per chain.
	
	Arguments:

	PDB_objects: list of PDB objects (with many chains) generated by the PDB parser.
	"""

	File_prefix = []

	for pdb in PDB_objects:
		chain_names = set()
		io = PDBIO()

		# Creates a PDB file for each chain of the original file.
		for chain in pdb.get_chains():
			if chain.get_id() not in chain_names:
				io.set_structure(chain)
				io.save(pdb.get_id() + "_" + chain.get_id() + ".pdb")
				File_prefix.append(pdb.get_id() + "_" + chain.get_id())

				# Creates a FASTA file for each chain of the original file.
				polipeptide = PPBuilder()
				for pp in polipeptide.build_peptides(pdb):
					fasta = open(pdb.get_id() + "_" + chain.get_id() + ".fa", "w")
					fasta.write(">" + pdb.get_id() + "_" + chain.get_id() + "\n")
					fasta.write(str(pp.get_sequence()))

				chain_names.add(chain.get_id())

	return File_prefix

def RunBLAST(db_path, prefix):
	"""
	Runs a psiBLAST application.

	Arguments:

	db_path: path to the pdb database.
	prefix: prefix of the input files to analyze and of the output files that will be generated.
	"""

	fasta = prefix + ".fa"
	xml = prefix + ".xml"
	pssm = prefix + "_pssm"

	Psi_query = Ncbicmd('psiblast', db = db_path, query = fasta, out = xml, evalue = 10, outfmt = 3, out_pssm = pssm)
	Psi_query() # Run BLAST.

	return xml

def SelectTemplate(BLAST_outs):
	"""
	Selects the best templates from the BLAST output for all chains.

	Arguments:

	BLAST_outs: list of output file names generated by BLAST.
	"""

	Outputs = {}

	for Out in BLAST_outs:
		BLAST_out = open(Out)
		First = True
		for line in BLAST_out:
			if line.startswith("Sequences producing significant alignments:"):
				BLAST_out.readline()
				for line in BLAST_out:
					line = line.strip()
					line = line.split()
					if First:
						min_evalue = line[len(line)-1]
						template_evalue = [(getNameWOChain(line[0]), line[len(line)-1])]
						Outputs[Out] = template_evalue
						First = False
					else:
						if line[len(line)-1] == min_evalue:
							template_evalue.append((getNameWOChain(line[0]), line[len(line)-1]))
							Outputs[Out] = template_evalue
						else:
							break
	# Select all possible best templates, the ones with the minimum evalue.
	min_evalue = min(map(lambda x: min(map(lambda y: y[1], x)), Outputs.values()))
	templates = set()
	for value in Outputs.values():
		for template in value:
			if template[1] == min_evalue:
				templates.add(template[0])

	return templates

def DownloadTemplate(template):
	"""
	Downloads the desired template from the pdb database. 

	Arguments:

	template: pdb code of the template to download.
	"""

	pdbl = PDBList()
	pdbl.retrieve_pdb_file(template, obsolete=False, pdir="./", file_format="pdb")

def CreateJoinedFastas(input_PDB_objects):
	"""
	Joins many PDB objects and creates a FASTA file with all objects joined.

	Arguments:

	input_PDB_objects: list of PDB objects which sequence will be added to the FASTA file.
	"""

	polipeptide = PPBuilder()
	first_line = True
	filename = ""

	# Create FASTA files.
	for obj in input_PDB_objects:
		filename = filename + obj.get_id() + "_"
	filename = filename + ".fa"
	joined_fasta = open(filename, 'w')

	# Write FASTA files.
	for obj in input_PDB_objects:
		if first_line:
			joined_fasta.write(">" + obj.get_id() + "\n")
			first_line = False
		else:
			joined_fasta.write("\n" + ">" + obj.get_id() + "\n")
		for polipep in polipeptide.build_peptides(obj):
			joined_fasta.write(str(polipep.get_sequence()))

	return filename

def RunClustal(fastas):
	"""
	Perform a multiple alignment running ClustalW.

	Arguments:

	fastas: list of FASTA files with all sequences to be aligned, ClustalW will be run for each one.
	"""

	for fasta in fastas:
		clustalw_cline = ClustalwCommandline("clustalw2", infile=fasta)
		stdout, stderr = clustalw_cline()
		with open(fasta.split(".")[0] + "ClustalScore.txt", 'w') as scores:
			scores.write(stdout)

def AnalizeClustalScore(sc_file, temp_name, score):
	"""
	Analyzes ClustalW output score files. 
	Selects the chains that align with an specific score or higher.

	Arguments:

	sc_file: name of the file containing the scores.
	temp_name: template name.
	score: desired score treshold.
	"""

	equivalences = {}
	aligns = []

	file = open(sc_file, 'r')

	equiv_reg = re.compile('(Sequence )([0-9]+)(: )(\S+)')
	alig_reg = re.compile('(Sequences \()([0-9]+)(:)([0-9]+)(\) Aligned. Score:  )([0-9]+)')
	
	for line in file:
		if re.match(equiv_reg, line):
			match = re.match(equiv_reg, line)
			equivalences[match[2]] = match[4]
			if match[4] == temp_name:
				template = match[2]
		elif re.match(alig_reg, line):
			alig = re.match(alig_reg, line)
			if (template == alig[2]) and (int(alig[6]) >= score):
				aligns.append(equivalences[alig[4]]) 
			elif (template == alig[4]) and (int(alig[6]) >= score):
				aligns.append(equivalences[alig[2]])

	return aligns

def FindInteractions(PDB_obj, inter):
	"""
	Find interactions or clashes between chains.

	Arguments:

	PDB_obj: PDB object in which we want to find interactions or clashes.
	inter: set to True if you want to find interactions. Set to False if you want to find clashes.
	"""

	if inter:
		interact_chains = []
		dist = 5.0
	else:
		dist = 0.4

	chains = Selection.unfold_entities(PDB_obj, 'C')
	obj_atoms = Selection.unfold_entities(PDB_obj, 'A')
	neighbors = NeighborSearch(obj_atoms)

	for chain in chains:
		atoms = Selection.unfold_entities(chain, 'A')
		for center in atoms: # For each atom as the center to compare distance to.
			interactions = neighbors.search(center.coord, dist ,level='C')
			if inter:
				ids = list(map(lambda x: x.get_id(), interactions))
				if len(ids) > 1:
					final_ids = list(filter(lambda x: x != chain.get_id(), ids))
					interact_chains.append((chain.get_id(), final_ids))
			else:
				for interact in interactions:
					if interact.get_id() != chain.get_id(): # If there is a clash between two diferent chains.
						return True
					else:
						continue
				return False
	if inter:
		return interact_chains

def getNameWOChain(whole_name):
	""" 
	Gets the name without the chain of a protein ID (name will be of the format "abc").
	
	Arguments:

	whole_name: name of the protein of format "abc_A"
	"""

	return whole_name[:-2]

def getTargInteractionKeys():
	"""
	Gets the keys of target interactions (from Final_interactions dictionary).
	"""

	return Final_interactions["target_interacts"].keys()

def getTempInteractionKeys(temp):
	"""
	Gets the keys of template interactions (from Final_interactions dictionary).
	"""
	return Final_interactions["temps"][temp]["temp_interact"].keys()

def getChain(whole_name):
	""" 
	Gets the chain name of a protein ID (chain name will be of the format "A").
	
	Arguments:

	whole_name: name of the protein of format "abc_A"
	"""

	return whole_name[-1:]

def getTempInteractions(temp_name, temp):
	"""
	Gets the values of the template interactions (from Final_interactions dictionary).
	"""

	return Final_interactions["temps"][temp]["temp_interact"][getChain(temp_name)]

def getTargetInteractions(targ_name):
	"""
	Gets the values of the target interactions (from Final_interactions dictionary).
	"""

	return Final_interactions["target_interacts"][getChain(targ_name)]

def AssignQueryToTemp(i, cand_list, temp_chains, Final_interactions, temp):
	"""
	Performs a backtracking to assign each chain of the template with a chain of the target.
	Takes into account the similarities between template-target chains and as a condition, 
	if two chains from the target interact, the two assigned chains from the template must also interact.

	Arguments:

	i: index of the recursivity. corresponding to the index of the target chains that is being assigned.
	cand_list: list of candidates (similarityes between template-target chains), 
		the list contains tupples where the first element is one chain and the second element is alist of candidates for this chain.
	temp_chains: dictionary of each chain of each template as keys and None as values at the beginnint,
		corresponding target chains will be saved in this dictionary.
	Final_interactions: dictionary containing the equivalencies between target-template chains, the target interactions and the template interactions.
	temp: tame of the actual tempalte.
	"""

	j = 0

	if i >= len(cand_list):
		return True
	else:
		targ = cand_list[i][0]
		while j < len(cand_list[i][1]):
			valid = True
			# Check if the actual template chain has not any target chain assigned yet.
			if temp_chains[cand_list[i][1][j]] == None: 
				temp_chains[cand_list[i][1][j]] = targ
				for prev_temp in temp_chains.keys():
					# In a target chain has previously been assigned.
					if temp_chains[prev_temp] != None and temp_chains[prev_temp] != targ:
						# If both target chains interact.
						if getChain(targ) in getTargInteractionKeys() and getChain(temp_chains[prev_temp]) in getTargInteractionKeys(): 
							if getChain(temp_chains[prev_temp]) in getTargetInteractions(targ) or getChain(targ) in getTargetInteractions(temp_chains[prev_temp]):
								# Both template chains must interact.
								if getChain(prev_temp) in getTempInteractionKeys(temp):
									if getChain(cand_list[i][1][j]) not in getTempInteractions(prev_temp, temp):
										valid = False
										break
								else: # Template chains do not interact.
									valid = False
									break
						elif getChain(targ) in getTargInteractionKeys():
							if getChain(temp_chains[prev_temp]) in getTargetInteractions(targ):
								# Both template chains must interact.
								if getChain(prev_temp) in getTempInteractionKeys(temp):
									if getChain(cand_list[i][1][j]) not in getTempInteractions(prev_temp, temp):
										valid = False
										break
								else: # Template chains do not interact.
									valid = False
									break
						elif getChain(temp_chains[prev_temp]) in getTargInteractionKeys():
							if getChain(targ) in getTargetInteractions(temp_chains[prev_temp]):
								# Both template chains must interact.
								if getChain(prev_temp) in getTempInteractionKeys(temp):
									if getChain(cand_list[i][1][j]) not in getTempInteractions(prev_temp, temp):
										valid = False
										break
								else: # Template chains do not interact.
									valid = False
									break
						else: # Template chains do not interact.
							valid = False
							break

				if valid:
					# Next recursive call
					if AssignQueryToTemp(i+1, cand_list, temp_chains, Final_interactions, temp):
						return True
				# The target chain is not well assigned so it must be emptied.		
				temp_chains[cand_list[i][1][j]] = None
			
			j += 1		
		return False

def I_AssignQueryToTemp(targ_chain_list, temp_chains, Final_interactions, temp):
	"""
	Performs an inmersion and performs the first recursive call.
	Assigns a list of candidate template chains to each target chain.

	Arguments:

	targ_chain_list: list of target chain names.
	temp_chains: dictionary of each chain of each template as keys and None as values at the beginnint,
		corresponding target chains will be saved in this dictionary.
	Final_interactions: dictionary containing the equivalencies between target-template chains, the target interactions and the template interactions.
	temp: tame of the actual tempalte.
	"""

	candidates = []
	temporal_cand = []

	# Crates a list of tuples (string, list of candidates).
	for target in targ_chain_list:
		for template in Final_interactions["temps"][temp]["target_temp"].keys():
			if target in Final_interactions["temps"][temp]["target_temp"][template]:
				temporal_cand.append(template)
		candidates.append((target, temporal_cand))
		if temporal_cand != []:
			temporal_cand = []
		else:
			return

	# First recursive call.
	AssignQueryToTemp(0, candidates, temp_chains, Final_interactions, temp)

def Superimpose_chains(temp_obj, PDB_bychain_objects, temp_chains):
	"""
	Superimposes each target chain atoms to the corresponding template chain atoms.

	Arguments:

	temp_obj: object of the current template.
	PDB_bychain_objects: list of PDB objects corresponding to each target chain.
	temp_chains: dictionary with the correspondencies of template-target chains.
	"""

	i = 0
	ref_model = temp_obj[0]
	ppbuild = PPBuilder()
	template_chains = Selection.unfold_entities(temp_obj, 'C')
	min_len1 = min(list(map(lambda x: len(ppbuild.build_peptides(x)[0].get_sequence()), template_chains)))
	min_len2 = min(list(map(lambda x: len(ppbuild.build_peptides(x)[0].get_sequence()), PDB_bychain_objects)))
	min_len = min([min_len1, min_len2])
	atoms_to_be_aligned = range(2, min_len)

	# Perform the superimposition for each target chain.
	for sample_structure in PDB_bychain_objects:
		sample_model = sample_structure[0]
		ref_atoms = []
		sample_atoms = []

		# Superimpose the target chain with it's corresponding template chain.
		for ref_chain in ref_model:
			for key, val in temp_chains.items():
				if val == sample_structure.get_id():
					if getNameWOChain(key) == temp_obj.get_id():
						temp_ch = key
			if temp_obj.get_id() + "_" + ref_chain.get_id() == temp_ch:
				for ref_res in ref_chain:
					if ref_res.get_id()[1] in atoms_to_be_aligned: # Ensure to superimpose the same number of atoms.
						ref_atoms.append(ref_res['CA']) # Take only C-alfa atoms.

		for sample_chain in sample_model:
			for sample_res in sample_chain:
				if sample_res.get_id()[1] in atoms_to_be_aligned: # Ensure to superimpose the same number of atoms.
					sample_atoms.append(sample_res['CA']) # Take only C-alfa atoms.

		# Superimpose.
		super_imposer = Superimposer()
		super_imposer.set_atoms(ref_atoms, sample_atoms)
		super_imposer.apply(sample_atoms)

		# Create a PDB file to save the new coordinates.
		io = PDBIO()
		io.set_structure(sample_structure)
		io.save(temp_obj.get_id() + "_" + str(i) + "_aligned.pdb", write_end = False)
		i += 1

	# Append each chain to a unique file.
	j = copy.copy(i)
	i = 1
	file = open(temp_obj.get_id() + "_0_aligned.pdb", 'a')
	final_files.append(temp_obj.get_id() + "_0_aligned.pdb")

	while i < j:
		file2 = open(temp_obj.get_id() + "_" + str(i) + "_aligned.pdb")
		for line in file2:
			file.write(line)
		i += 1

if __name__ == "__main__":

	from Bio.PDB import PDBParser, PDBIO, PPBuilder, Superimposer,PDBList, NeighborSearch, Selection
	from Bio.Blast.Applications import NcbipsiblastCommandline as Ncbicmd
	from Bio.Align.Applications import ClustalwCommandline
	import copy
	import numpy
	import re

	parser = argparse.ArgumentParser(description="blah")

	parser.add_argument('-i', '--input',
				dest= "infiles",
				action= "store",
				required = True,
				nargs = "+",
				help="Input file names (PDB files with pairs of chains that interact), insert as many as needed.")
	parser.add_argument('-d', '--database',
				dest= "database",
				action= "store",
				required = True,
				help="Path to the pdb database in your computer.")
	
	options=parser.parse_args()

	# INITIALIZATING SOME VARIABLES

	# Dictionary with all interactions between chains and correspondency with target-template chians
	Final_interactions = {}
	Final_interactions["target_interacts"] = {}
	Final_interactions["temps"] = {}
	# Input chains
	already_added = []
	unique_chains = []
	# Templates
	BLAST_outs = []
	fasta_names = []
	temp_chains = {}
	#Output
	final_files = []
	correct_predictions = []

	# WORKING WITH THE INPUT

	# Parse input files.
	(PDB_input_objects, PDB_input_names) = ParsePDB(options.infiles)
	file_prefixes = SplitChain(PDB_input_objects)

	# Save the names of the input chains.
	first = True
	for pref in file_prefixes:
		if first:
			unique_chains.append(pref)
			already_added.append(pref.split("_")[1])
			first = False
		if pref.split("_")[1] not in already_added:
			unique_chains.append(pref)
			already_added.append(pref.split("_")[1])

	# Parse the pdb files with single chains
	bychain_PDBs = map(lambda x: x + ".pdb", unique_chains)
	(PDB_bychain_objects, PDB_bychain_names) = ParsePDB(bychain_PDBs)
	# Add data to Final_interactions dictionary
	for inp in PDB_input_objects:
		inp_chains = inp.get_chains()
		inp_chains_ids = list(map(lambda x: x.get_id(), inp_chains))
		if inp_chains_ids[0] not in Final_interactions["target_interacts"].keys():
			Final_interactions["target_interacts"][inp_chains_ids[0]] = list(inp_chains_ids[1])
		elif (inp_chains_ids[0] in Final_interactions["target_interacts"].keys()) and (inp_chains_ids[1] not in Final_interactions["target_interacts"][inp_chains_ids[0]]):
			Final_interactions["target_interacts"][inp_chains_ids[0]].append(inp_chains_ids[1])

	# WORKING WITH TEMPLATES

	# Look for templates
	for prefix in file_prefixes:
		output = RunBLAST(options.database, prefix)
		BLAST_outs.append(output)
	Templates = SelectTemplate(BLAST_outs)

	# Downloading, parsing and spliting by chain the templates
	for template in Templates:
		DownloadTemplate(template)
	temp_PDBs = map(lambda x: "pdb" + x + ".ent", Templates)
	(PDB_temp_objs, PDB_temp_names) = ParsePDB(temp_PDBs)	
	template_chains = SplitChain(PDB_temp_objs)
	bychain_PDBs = map(lambda x: x + ".pdb", template_chains)
	(PDB_chain_temp_objs, PDB_chain_temp_names) = ParsePDB(bychain_PDBs)

	# MODELING

	# Creating a fasta file for each template chain adding all the input chains
	for chain in PDB_chain_temp_objs:
		obj_list = copy.copy(PDB_bychain_objects)
		obj_list.append(chain)
		joined_file = CreateJoinedFastas(obj_list)
		fasta_names.append(joined_file)
	# Performing a multiple alignment with ClustalW
	RunClustal(fasta_names)
	# Add data to Final_interactions dictionary
	first = True
	for fa_name in fasta_names:
		temp_name = fa_name.split("_")[-3] + "_" + fa_name.split("_")[-2]
		if first:
			tmp = getNameWOChain(temp_name)
			Final_interactions["temps"][getNameWOChain(temp_name)] = {}
			Final_interactions["temps"][getNameWOChain(temp_name)]["target_temp"] = {}
			first = False
		temp_chains[temp_name] = None
		aligns = AnalizeClustalScore(fa_name.split(".")[0] + "ClustalScore.txt", temp_name, 100)
		if len(aligns) == 0:
			aligns = AnalizeClustalScore(fa_name.split(".")[0] + "ClustalScore.txt", temp_name, 90)
			if len(aligns) == 0:
				aligns = AnalizeClustalScore(fa_name.split(".")[0] + "ClustalScore.txt", temp_name, 50)
				if len(aligns) == 0:
					print("Obtained templates are not good enough to trust the models, consider to use another approach to solve your problem.")
					aligns = AnalizeClustalScore(fa_name.split(".")[0] + "ClustalScore.txt", temp_name, 0)
		if tmp == getNameWOChain(temp_name):
			Final_interactions["temps"][getNameWOChain(temp_name)]["target_temp"][temp_name] = aligns
		else:
			Final_interactions["temps"][getNameWOChain(temp_name)] = {}
			Final_interactions["temps"][getNameWOChain(temp_name)]["target_temp"] = {}
			Final_interactions["temps"][getNameWOChain(temp_name)]["target_temp"][temp_name] = aligns
			tmp = getNameWOChain(temp_name)
			
		Final_interactions["temps"][temp_name[:-2]]["temp_interact"] = {}
		temp_obj = list(filter(lambda x: x.get_id() == getNameWOChain(temp_name), PDB_temp_objs))
		list_interacts = FindInteractions(temp_obj[0], True)
		for interact in list_interacts:
			if interact[0] in Final_interactions["temps"][temp_name[:-2]]["temp_interact"].keys():
				Final_interactions["temps"][getNameWOChain(temp_name)]["temp_interact"][interact[0]].update(interact[1])
			else:
				Final_interactions["temps"][getNameWOChain(temp_name)]["temp_interact"][interact[0]] = set(interact[1])

	# Using a backtracking to assign chain relations (target-template)
	for temp in PDB_temp_names:
		I_AssignQueryToTemp(PDB_bychain_names, temp_chains, Final_interactions, temp)

	# Superimposing the chains
	for temp_obj in PDB_temp_objs:
		try:
			Superimpose_chains(temp_obj, PDB_bychain_objects, temp_chains)
		except Exception:
			pass


	# FINAL ANALYSIS OF THE OBTAINED MODELS

	# Analyzing obtained models
	(PDB_final_objects, PDB_final_names) = ParsePDB(final_files)
	for final_obj, final_name in zip(PDB_final_objects, PDB_final_names):
		if not FindInteractions(final_obj, False):
			correct_predictions.append(final_name)

	print("The generated files with the models are called: \n%s \nFeel free to further analyse the models and choose the one that you find more accurate." %(correct_predictions))
