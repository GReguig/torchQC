""" End-to-end segmentation pipeline """
import json
import argparse
import matplotlib.pyplot as plt
from segmentation.data import load_data, generate_dataset, generate_dataloader
from segmentation.model import load_model, train
from segmentation.visualization import parse_visualization_config_file
from plot_dataset import PlotDataset


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('-f', '--file', type=str, help='Path to configuration file')
    parser.add_argument('-m', '--mode', type=str, default='train', help='Training or inference mode')
    parser.add_argument('-viz', '--visualization', type=int, default=0,
                        help='Visualization, 1 means that full images will be shown, 2 means that patches will be '
                             'shown, higher values mean full images with patches will be shown')
    parser.add_argument('-v', '--verbose', type=int, default=0, help='Verbosity, the higher the more verbose')
    args = parser.parse_args()

    # Load main configuration file
    with open(args.file) as file:
        info = json.load(file)

    # Get all configuration files from main file
    folder = info.get('folder')
    data_filename = info.get('data')
    transform_filename = info.get('transform')
    loader_filename = info.get('loader')
    model_filename = info.get('model')
    train_filename = info.get('train')
    test_filename = info.get('test')
    visualization_filename = info.get('visualization')

    # Generate datasets and data loaders
    train_subjects, val_subjects, test_subjects = load_data(folder, data_filename)

    train_set = generate_dataset(train_subjects, folder, transform_filename)
    val_set = generate_dataset(val_subjects, folder, transform_filename, prefix='val')
    test_set = generate_dataset(test_subjects, folder, transform_filename, prefix='val')

    train_loader = generate_dataloader(train_set, folder, loader_filename)
    val_loader = generate_dataloader(val_set, folder, loader_filename)
    test_loader = generate_dataloader(test_set, folder, loader_filename)

    # Visualize data
    if args.visualization > 0:
        kwargs = parse_visualization_config_file(folder, visualization_filename)
        if args.visualization == 1:
            fig = PlotDataset(train_set, **kwargs)
        elif args.visualization == 2:
            _, batch = next(enumerate(train_loader))
            fig = PlotDataset(batch, **kwargs)
        elif args.visualization > 2:
            print('Be careful, if random transforms are applied without seed, patches will not match full images.')
            _, batch = next(enumerate(train_loader))
            fig = PlotDataset(train_set, batch=batch, batch_mapping_key='name', **kwargs)
        plt.show()

    # Load model
    model = load_model(folder, model_filename)

    # Train model
    if args.mode == 'train':
        train(model, train_loader, val_loader, val_set, folder, train_filename)

    # Infer results on test data
    else:
        pass
