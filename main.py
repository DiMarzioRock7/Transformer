import argparse
import time
import torch
import torch.nn as nn
import torch.onnx

from dataloader import get_dataloader
from transformer.Models import Transformer
from epoch import train, evaluate


def main():
    parser = argparse.ArgumentParser(description='Transformer project')

    # model setting
    parser.add_argument('--n_layer', type=int, default=3,
                        help='number of transformer encoder layer')
    parser.add_argument('--d_model', type=int, default=256,
                        help='model feature dimension')
    parser.add_argument('--n_head', type=int, default=8,
                        help='number of attention heads')
    parser.add_argument('--d_inner', type=int, default=1024,
                        help='hidden representation size of the feed-forward layer')
    parser.add_argument('--scaled_attn', type=bool, default=False,
                        help='scale attention in multi-head attention layer')

    # preprocess
    parser.add_argument('--pad_number', type=bool, default=True,
                        help='pad all numbers to a same <num>')
    parser.add_argument('--lower_char', type=bool, default=True,
                        help='lower cases of characters')
    parser.add_argument('--weight_sharing', type=int, default=1,
                        help='sharing weights of predictor and embedding:'
                             '0 -> weight not sharing'
                             '1 -> weight sharing with learnable bias'
                             '2 -> weight sharing with no bias'
                             'others -> embedding inner-product')

    # training settings
    parser.add_argument('--n_gram', type=int, default=25,
                        help='max input sequence length')
    parser.add_argument('--num_worker', type=int, default=15,
                        help='number of dataloader worker')
    parser.add_argument('--batch_size', type=int, default=1000, metavar='N',
                        help='batch size')
    parser.add_argument('--epochs', type=int, default=10,
                        help='upper epoch limit')
    parser.add_argument('--dropout', type=float, default=0.1,
                        help='dropout rate applied to layers (0 = no dropout)')
    parser.add_argument('--lr', type=float, default=1e-3,
                        help='initial learning rate')
    parser.add_argument('--lr_step', type=int, default=20,
                        help='number of epoch for each lr downgrade')
    parser.add_argument('--lr_gamma', type=float, default=0.1,
                        help='strength of lr downgrade')
    parser.add_argument('--es_patience_max', type=int, default=3,
                        help='max early stopped patience')
    parser.add_argument('--eps_loss', type=float, default=0,
                        help='minimum loss difference threshold')

    # file settings
    parser.add_argument('--seed', type=int, default=1111,
                        help='random seed')
    parser.add_argument('--device', type=str, default='cuda:0',
                        help='device for computing')
    parser.add_argument('--path_data', type=str, default='./data/wikitext-2/',
                        help='path of the data corpus')
    parser.add_argument('--path_data_processed', type=str, default='./data/wikitext-2/data.pkl',
                        help='path of the processed data')
    parser.add_argument('--path_model', type=str, default='./result/models/model.pt',
                        help='path of the trained model')

    args = parser.parse_args()
    args.path_model += args.device[-1]
    args.device = torch.device(args.device)
    args.d_k = args.d_v = args.d_model // args.n_head  # key and value representation size

    print('\n[info] Project starts...')
    print('\n[info] Load dataset and other resources...')
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)

    # prepare data and model
    vocab, train_loader, valid_loader, test_loader = get_dataloader(args)
    args.n_word = len(vocab)

    model = Transformer(args).to(args.device)
    args.criterion = nn.CrossEntropyLoss()

    optimizer = torch.optim.Adam(filter(lambda x: x.requires_grad, model.parameters()), lr=args.lr,
                                 weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=args.lr_step, gamma=args.lr_gamma)

    n_param_encoder = sum(p.numel() for p in model.encoder.parameters() if p.requires_grad)

    # Start modeling
    print('\n[info] | n_param {n_param} | n_layer {n_layer} | d_model {d_model} | n_head {n_head} | d_k {d_k} | '
          'd_inner {d_inner} | n_gram {n_gram} |'
          .format(n_param=n_param_encoder, n_layer=args.n_layer, d_model=args.d_model, n_head=args.n_head, d_k=args.d_k,
                  d_inner=args.d_inner, n_gram=args.n_gram))
    best_loss_val = 1e5
    best_epoch = 0
    es_patience = 0

    for epoch in range(1, args.epochs+1):
        print('\n[Epoch {epoch}]'.format(epoch=epoch))

        # training phase
        t_start = time.time()
        loss_train = train(args, model, train_loader, optimizer)
        scheduler.step()
        print('  | Train | loss {:5.4f} | ppl {:5.4f} | {:5.2f} s |'
              .format(loss_train, torch.exp(loss_train), time.time() - t_start))

        # validating phase
        loss_val = evaluate(args, model, valid_loader)
        if loss_val < best_loss_val:
            if best_loss_val - loss_val > args.eps_loss:
                es_patience = 0  # reset if beyond threshold
            with open(args.path_model, 'wb') as f:
                torch.save(model, f)
            best_loss_val = loss_val
            best_epoch = epoch
        else:
            # Early stopping condition
            es_patience += 1
            if es_patience >= args.es_patience_max:
                print('\n[Warning] Early stopping model')
                print('  | Best | epoch {:d} | loss {:5.4f} | ppl {:5.4f} |'
                      .format(best_epoch, best_loss_val, torch.exp(best_loss_val)))
                break
        # logging
        print('  | Valid | loss {:5.4f} | ppl {:5.4f} | es_patience {:.0f}/{:.0f} |'
              .format(loss_val, torch.exp(loss_val), es_patience, args.es_patience_max))

    # testing phase
    print('\n[Testing]')
    with open(args.path_model, 'rb') as f:
        model = torch.load(f)
    loss_test = evaluate(args, model, test_loader)

    print('  | Test | loss {:5.4f} | ppl {:5.4f} |'
          .format(loss_test, torch.exp(loss_test)))
    print('\n[info] | n_param {n_param} | n_layer {n_layer} | d_model {d_model} | n_head {n_head} | d_k {d_k} | '
          'd_inner {d_inner} | n_gram {n_gram} |\n'
          .format(n_param=n_param_encoder, n_layer=args.n_layer, d_model=args.d_model, n_head=args.n_head, d_k=args.d_k,
                  d_inner=args.d_inner, n_gram=args.n_gram))


if __name__ == '__main__':
    main()
