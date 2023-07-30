import os
import copy
import json
import torch
from pathlib import Path
import numpy as np
from tqdm import tqdm
from torch import utils
from config import config
from config import ex, config
from InternVideo import tokenize
from Model import AfricanSlowfast
from open_clip import _build_vision_tower
from Dataset import AnimalKingdomDatasetPreprocess

def collate_func(batch):
    video_tensors = [item[0] for item in batch]
    video_tensors_n_frames = [video_tensor_fast.shape[0] for video_tensor_fast in video_tensors]
    video_tensors_cat = torch.cat(video_tensors, dim=0)
    video_fps = [item[1] for item in batch]  # each element is of size (1, h*, w*). where (h*, w*) changes from mask to another.
    return video_tensors_cat, video_tensors_n_frames, video_fps

def inference_save(_config, dataset, dataloader, image_encoder):
    """dataloader without collate function with only batch_size=1"""
    with torch.no_grad():
        for batch_idx, (video_tensors_fast, video_fps) in enumerate(tqdm(dataloader)):
            video_tensors_fast = video_tensors_fast.to(_config['device'])
            for idx, (video_tensor_fast, video_fp) in enumerate(zip(video_tensors_fast, video_fps)):
                video_feats_fast_fp = dataset.get_preprocess_feats_fp(video_fp)
                if not os.path.exists(video_feats_fast_fp):
                    video_feats_fast = image_encoder(video_tensor_fast)
                    torch.save(video_feats_fast, video_feats_fast_fp)

def batch_inference_save(_config, dataset, dataloader, image_encoder, pretrained_type):
    if pretrained_type == 'ic':
        transformer_width = _config['transformer_width_ic']
    elif pretrained_type == 'af':
        transformer_width = _config['transformer_width_af']

    with torch.no_grad():
        for batch_idx, (batch) in enumerate(tqdm(dataloader)):
            video_tensors_cat, video_tensors_n_frames, video_fps = batch
            all_exists = np.all([os.path.exists(dataset.get_preprocess_feats_fp(video_fp, pretrained_type)) for video_fp in video_fps])
            if all_exists:
                continue

            # parallel inference
            video_tensors_cat = video_tensors_cat.to(_config['device'])
            video_feats_tensors_cat = torch.zeros(video_tensors_cat.shape[0], transformer_width)
            n_iters = int(np.ceil(video_feats_tensors_cat.shape[0] / _config['preprocess_batch_size']))
            for idx in range(n_iters):
                st, end = idx*_config['preprocess_batch_size'], (idx+1)*_config['preprocess_batch_size']
                video_tensors_batch = video_tensors_cat[st:end]
                video_feats_tensors_batch = image_encoder(video_tensors_batch)
                video_feats_tensors_cat[st:end] = video_feats_tensors_batch

            # split into different videos $ save
            frane_st = 0
            for idx, (n_frames, video_fp) in enumerate(zip(video_tensors_n_frames, video_fps)):
                video_feats_fast = video_feats_tensors_cat[frane_st: frane_st+n_frames]
                frane_st = frane_st+n_frames

                video_feats_fast_fp = dataset.get_preprocess_feats_fp(video_fp, pretrained_type)
                if not os.path.exists(video_feats_fast_fp):
                    torch.save(video_feats_fast, video_feats_fast_fp)


@ex.automain
def main(_config):
    _config = copy.deepcopy(_config)

    for pretrained_type in _config['preprocess_pretrained_type']: 
        dataset_train = AnimalKingdomDatasetPreprocess(_config, pretrained_type, split="train")
        dataset_valid = AnimalKingdomDatasetPreprocess(_config, pretrained_type, split="val")

        _config['max_steps'] = _config['max_epochs'] * len(dataset_train) // _config['batch_size']
        model = AfricanSlowfast(_config).to(_config['device'])
        dataset_train.produce_prompt_embedding(model.video_clip)
        dataset_valid.produce_prompt_embedding(model.video_clip)

        train_loader = utils.data.DataLoader(dataset_train, batch_size=_config['batch_size'], collate_fn=collate_func, shuffle=False) # _config['batch_size']
        valid_loader = utils.data.DataLoader(dataset_valid, batch_size=_config['batch_size'], collate_fn=collate_func, shuffle=False) # _config['batch_size']

        image_encoder_fast = model.get_image_encoder_fast(_config, pretrained_type)
        image_encoder_fast.to(_config['device'])
        image_encoder_fast.eval()

        batch_inference_save(_config, dataset_train, train_loader, image_encoder_fast, pretrained_type)
        batch_inference_save(_config, dataset_valid, valid_loader, image_encoder_fast, pretrained_type)

        # inference_save(_config, dataset_train, train_loader, image_encoder_fast)
        # inference_save(_config, dataset_valid, valid_loader, image_encoder_fast)



# check the preprocessed result from diff branch are the same
# import glob
# import torch
# from tqdm import notebook
# import sys 
# sys.path.append("/notebooks/AnimalKingdomCLIP/Train")
# from VideoReader import read_feats_fast

# feats_fp_new = glob.glob("/notebooks/AnimalKingdomCLIP/Train/preprocess_test/ViT-L-14/*.pt")
# for idx, feat_fp_new in enumerate(notebook.tqdm(feats_fp_new)):
#     feat_fp_old = feat_fp_new.replace("preprocess_test/ViT-L-14", "preprocess/video_feats/ViT-L-14")
#     feat_old = torch.load(feat_fp_old).to('cpu')
#     feat_new = torch.load(feat_fp_new).to('cpu')
#     if not torch.all(torch.isclose(feat_old, feat_new, rtol=1e-05, atol=1e-05)):
#         neq_idxs = torch.where(torch.isclose(feat_old, feat_new, rtol=1e-05, atol=1e-05) == False)
#         print(idx)
#         print(feat_old.shape, feat_new.shape)
#         print(feat_old[neq_idxs][:10], feat_new[neq_idxs][:10])
#         print(feat_old)
#         print(feat_new)
#         print("===========")
    

# import glob
# import torch
# from tqdm import tqdm
# import sys 
# sys.path.append("/notebooks/AnimalKingdomCLIP/Train")
# from VideoReader import read_feats_fast

# feats_fp_new = glob.glob("/notebooks/AnimalKingdomCLIP/Train/preprocess/ViT-L-14/*.pt")
# feats_fp_new = glob.glob("/notebooks/AnimalKingdomCLIP/Train/preprocess/uniform_32/*.pt")
# for idx, feat_fp_new in enumerate(tqdm(feats_fp_new)):
#     feat_fp_old = feat_fp_new.replace("ViT-L-14", "uniform_32")
#     feat_old = torch.load(feat_fp_old).to('cpu')
#     feat_new = torch.load(feat_fp_new).to('cpu')
#     if not torch.all(torch.isclose(feat_old, feat_new, rtol=1e-05, atol=1e-05)):
#         neq_idxs = torch.where(torch.isclose(feat_old, feat_new, rtol=1e-05, atol=1e-05) == False)
#         print(idx)
#         print(feat_old.shape, feat_new.shape)
#         print(feat_old[neq_idxs][:10], feat_new[neq_idxs][:10])
#         print(feat_old)
#         print(feat_new)
#         print("===========")
