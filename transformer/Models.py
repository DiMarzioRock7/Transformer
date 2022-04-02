import copy
import torch
import torch.nn as nn
from utils import init_embedding, init_linear

from transformer.Layers import PositionalEncoding, Encoder, Decoder


class Transformer(nn.Module):
    def __init__(self, args):
        super(Transformer, self).__init__()
        self.device = args.device
        self.n_layer = args.n_layer
        self.d_model = args.d_model
        self.d_inner = args.d_inner
        self.n_head = args.n_head
        self.d_k = args.d_k
        self.d_v = args.d_v
        self.dropout = args.dropout

        self.n_word = args.n_word
        self.n_gram = args.n_gram

        # subsequent mask, our sequence length are fixed
        self.subsequent_mask = (1 - torch.triu(
            torch.ones((1, self.n_gram, self.n_gram), device=self.device), diagonal=1)).bool()

        # embedding layer
        self.embedding = nn.Embedding(self.n_word, self.d_model)
        init_embedding(self.embedding)
        self.pos_enc = PositionalEncoding(self.d_model, self.n_gram, self.device)
        self.dropout1 = nn.Dropout(p=self.dropout)
        self.layer_norm = nn.LayerNorm(self.d_model, eps=1e-6)

        # transformer
        self.encoder = Encoder(self.n_layer, self.d_model, self.d_inner, self.n_head, self.d_k, self.d_v, self.dropout)
        self.decoder = Decoder(self.n_layer, self.d_model, self.d_inner, self.n_head, self.d_k, self.d_v, self.dropout)

        # predictor
        self.weight_sharing = args.weight_sharing
        if self.weight_sharing == 0:
            # 0 -> weight sharing with bias
            self.fc1 = nn.Linear(self.d_model, self.n_word, bias=True)
            self.fc1.weight = self.embedding.weight

        elif self.weight_sharing == 1:
            # 1 -> weight sharing without bias
            self.fc1 = nn.Linear(self.d_model, self.n_word, bias=False)
            self.fc1.weight = self.embedding.weight

        elif self.weight_sharing == 2:
            # 2 -> weight not sharing
            self.fc1 = nn.Linear(self.d_model, self.n_word, bias=True)
            init_linear(self.fc1)

        else:
            # others -> embedding inner-product
            self.fc1 = None

    def forward(self, seq_batch):

        inputs = self.embedding(seq_batch)
        inputs += self.pos_enc(inputs)
        inputs = self.dropout1(inputs)
        inputs = self.layer_norm(inputs)

        enc_outputs, enc_slf_attn = self.encoder(inputs, slf_attn_mask=self.subsequent_mask)
        dec_outputs, dec_slf_attn, dec_enc_attn = self.decoder(inputs, enc_outputs)

        if self.fc1:
            outputs = self.fc1(dec_outputs[:, -1, :].squeeze(1))
        else:
            outputs = torch.mm(dec_outputs[:, -1, :], self.embedding.weight.T)

        return outputs, enc_slf_attn, dec_slf_attn, dec_enc_attn


