'''
Created on Jul 16, 2019

@author: 
This file is a modified version of https://github.com/Duke-GCB/Predict-TF-Binding
'''
from sitesfinder.sitesfinder import SitesFinder
from sitesfinder.imadsmodel import iMADSModel
import util.bio as bio
import itertools
import math
import matplotlib.patches as patches
from sitesfinder.prediction.basepred import BasePrediction

class iMADS(SitesFinder):
    '''
    classdocs
    '''
    def __init__(self, imads_models, imads_threshold):
        """
        Desc
        :param imads_models: a list of models 
        :param flank_colname: must be a column name where the direction can be obtained using
                              flank_colname + _left/_right
        """
        if not isinstance(imads_models, list) or not isinstance(imads_models[0], iMADSModel):
            raise Exception('imads_models must be a list of iMADSModel')
        self.models = imads_models #temporary use 0
        self.imads_threshold = imads_threshold

    #def generate_matching_sequence(self, sequence, core, width):

    def generate_matching_sequence(self, sequence, core, width):
        """
        Returns sub-sequences of width, that match the core in the middle.
        :param sequence: The the sequence to search, such as the whole sequence for a chromosome.
                Can be a string or a Bio.Seq
        :param core: The bases for which to search, in the center
        :param width: The desired sub-sequence width, e.g. 36
        :return: Generator, returning one sub-sequence per call
        """
        
        # Need to search for core and reverse complement in the window region
        # If RC is found in the region, return the reverse-complement of the window instead
        # Also, if core is palindromic, need to return both regions and return best score
        core_rc = bio.revcompstr(core)
        max_start = len(sequence) - width
        core_start = (width - len(core)) // 2
        for start in range(max_start + 1):
            end = start + width
            window_sequence = sequence[start:end]
            # If any of the bases in the window are unknown, we cannot predict on the sequence
            if 'N' in window_sequence:
                continue
            window_core = window_sequence[core_start:core_start + len(core)]
            #print("seq and core",window_sequence,window_core)
            # If core is palindromic, return two sequences and let the caller decide which to use
            core_pos = core_start + start
            if core == core_rc and window_core == core:
                yield start, core_pos, (str(window_sequence), str(bio.revcompstr(window_sequence)),)
            elif window_core == core:
                yield start, core_pos, (window_sequence,)
            elif window_core == core_rc:
                yield start, core_pos, (str(bio.revcompstr(window_sequence)),)
                
    def svr_features_from_sequence(self, seq, kmers):
        """
        Transforms a sequence and list of kmer values into a list of dictionaries
        that be converted easily into an SVR matrix.
    
        kmers is a list of lengths. For each length, the function will enumerate all possible
        nucleotide combinations at that length ('AA','AC','AG',...'TT')
    
        The function returns a list of all possible positions in the sequence x all possible features
        and indicates 1 if the feature matches that position in the sequence, or 0 if it does not.
    
        For example, for the input sequence 'ACAGTC' and a kmer value of [2,3], the function
         produces the following
    
        [{'position': 0, 'value': 0, 'feature': 'AA'}, # 'AA' does not match at position 0
         {'position': 0, 'value': 1, 'feature': 'AC'}, # 'AC' matches at position 0 in 'ACAGTC'
         {'position': 0, 'value': 0, 'feature': 'AG'},
         ...
         {'position': 1, 'value': 1, 'feature': 'CA'}, # 'CA' matches at position 1 in 'ACAGTC'
         ...
         {'position': 0, 'value': 0, 'feature': 'AAT'},
         {'position': 0, 'value': 1, 'feature': 'ACA'},
         {'position': 0, 'value': 0, 'feature': 'ACC'},
    
        :param seq: A sequence of nucleotides to expand
        :param kmers: list of integers (e.g. [1,2,3])
        :return: a list of dictionaries, containing position, featvalue, and feature
        """
        NUCLEOTIDES='ACGT'
        
        str_seq = str(seq) # If seq is a Bio.Seq, it's faster to check it as a string
        svr_features = []
        for k in kmers:
            # Generate all possible combinations of length k (e.g ['AAA', 'AAC', ...  'TTG', 'TTT']
            features = [''.join(x) for x in itertools.product(NUCLEOTIDES, repeat=k)]
            # Check each position in the sequence for a match
            n_sub_seqs = len(str_seq) - (k - 1) # If seq length is 36 and k is 3, there are 34 positions
            for position in range(n_sub_seqs):
                sub_seq = str_seq[position:position + k] # the sub-sequence with length k
                # start with a template list. All zero values at the current position
                exploded = [{'feature': feature, 'position': position, 'value': 0} for feature in features]
                # Determine the index of the current sub seq
                try:
                    feature_index = features.index(sub_seq)
                    exploded[feature_index]['value'] = 1
                except ValueError:
                    print("Warning: sub-sequence '{}' not found in features".format(sub_seq))
                svr_features.extend(exploded)
        return svr_features

    def transform_score(self, score):
        # f(x) = 1 / ( 1 + exp(-x) )  to obtain only values between 0 and 1.
        return 1.0 / (1.0 + math.exp(0.0 - score))
        
    def predict_sequence(self, sequence, model, const_intercept, transform_scores):
        for position, core_pos, matching_sequences in self.generate_matching_sequence(sequence, model.core, model.width):
            # generator returns a position, and a tuple of 1 or 2 sequences
            # If two sequences are returned, core is palindromic and can bind on either strand
            # So generate predictions for both and return the best
            # 4. Translate the sequences into SVR matrix by kmers
            best_prediction = None
            best_match = None
            for matching_sequence in matching_sequences:
                features = self.svr_features_from_sequence(matching_sequence, model.kmers)
                predictions, accuracy, values = model.predict(features, const_intercept)
                if best_prediction is None or predictions[0] > best_prediction:
                    best_prediction = predictions[0]
                    best_match = matching_sequence
            if best_prediction is None:
                continue
            if transform_scores:
                best_prediction = self.transform_score(best_prediction)
            yield {"site_start": position, "site_width": model.width,
                   "best_match":best_match, "score":best_prediction,
                   "core_start": core_pos, "core_width": len(model.core)
                   }
    
    # or predict fasta?
    def predict_sequences(self, sequence_df, const_intercept=False, transform_scores=True, sequence_colname="sequence", flank_colname="flank"):
        """
        do not make this as generator, because we need to use it somewhere elsee
        """
        seqdict = self.pred_input_todict(sequence_df, sequence_colname=sequence_colname)
        flank_left = bio.get_seqdict(sequence_df,"%s_left" % flank_colname)
        flank_right = bio.get_seqdict(sequence_df,"%s_left" % flank_colname)
        predictions = {}
        for key in seqdict:
            sequence = flank_left[key] + seqdict[key] + flank_right[key]
            prediction = []
            for model in self.models:
                for result in self.predict_sequence(sequence, model, const_intercept, transform_scores):
                    # we need to have the start position relative to the main sequence instead of the flank
                    result['site_start'] = result['site_start'] - len(flank_left[key])
                    result['core_start'] = result['core_start'] - len(flank_left[key])
                    prediction.append(result)
            predictions[key] = BasePrediction(sequence, prediction)
        return predictions

    def plot(self, predictions_dict):
        #predictions = self.predict_sequences(sequence_df, const_intercept, 
        #                                    transform_scores, sequence_colname, flank_colname)
        func_dict = {}
        for key in predictions_dict:
            sequence = predictions_dict[key].sequence
            sites_prediction = predictions_dict[key].predictions
            func_pred = []
            for pred in sites_prediction:
                # first argument is x,y and y is basically just starts at 0
                # first plot the binding site
                # Note that it is important to do -1 on rectangle width so we only cover the site
                site_rect = patches.Rectangle((pred["site_start"],0),pred["site_width"] - 1,pred["score"],
                                 facecolor="mediumspringgreen",alpha=0.6,edgecolor='black')
                func_pred.append({"func":"add_patch","args":[site_rect],"kwargs":{}})
                # then plot the core
                core_rect = patches.Rectangle((pred["core_start"],0),pred["core_width"] - 1,pred["score"],
                                 facecolor="mediumspringgreen",alpha=0.9,edgecolor='black')
                func_pred.append({"func":"add_patch","args":[core_rect],"kwargs":{}})
            func_pred.append({"func":"axhline","args":[self.imads_threshold],
                              "kwargs": {"color" : "seagreen", 
                                        "linestyle" : "dashed",
                                        "linewidth" : 1}})
            func_dict[key] = {"sequence":sequence,
                              "plt":func_pred}
        return func_dict
        
        