import json
import torch
from torchio import Subject, Image
import torchio
import dash
import dash_core_components as dcc
import dash_html_components as html
from dash.dependencies import Input, Output
import os
import pandas as pd
import inspect
import nibabel as nb
from pathlib import PosixPath
import plotly.graph_objects as go
import matplotlib.pyplot as plt
plt.interactive(True)
from os.path import join as opj
from .segmentation.utils import custom_import


class ModelCSVResults(object):

    def __init__(self, csv_path=None, out_tmp=""):
        self.csv_path = csv_path
        self.df_data = None
        self.out_tmp = out_tmp
        if csv_path:
            self.open(csv_path=csv_path)
        self.dash_app = None
        self.written_files = []

    def open(self, csv_path):
        self.df_data = pd.read_csv(csv_path)

    def close(self):
        del self.df_data
        self.csv_path = None
        self.df_data = None

    def get_row(self, idx):
        return self.df_data.iloc[idx]

    def read_path(self, path):
        if isinstance(path, list):
            return self.read_path(path[0])

        elif isinstance(path, PosixPath):
            return opj(str(path))

        elif isinstance(path, str):
            try:
                eval_path = eval(path)
                return self.read_path(eval_path)
            except NameError:
                return opj(eval_path)

        else:
            raise TypeError("Could not read path: {}".format(path))

    def get_volume_nibabel(self, idx, return_orig=False):
        subject_row = self.get_row(idx)
        subject_path = self.read_path(subject_row["image_filename"])
        if return_orig:
            volume = nb.load(subject_path)
        else:
            tio_data = self.get_volume_torchio(idx, return_orig=return_orig)["volume"]
            data, affine = tio_data["data"], tio_data["affine"]
            volume = nb.Nifti1Image(data, affine)
        return volume

    def get_volume_torchio(self, idx, return_orig=False):
        subject_row = self.get_row(idx)
        subject_path = self.read_path(subject_row["image_filename"])
        sub = Subject({"volume": Image(subject_path)})
        if return_orig:
            return sub
        else:
            trsfms, seeds = self.get_transformations(idx)
            res = trsfms(sub, seeds)
            for tr in trsfms.transform.transforms:
                if isinstance(tr, torchio.RandomMotionFromTimeCourse):
                    output_path = opj(self.out_tmp, "{}.png".format(idx))
                    fitpars = tr.fitpars
                    plt.figure()
                    plt.plot(fitpars.T)
                    plt.legend(["trans_x", "trans_y", "trans_z", "rot_x", "rot_y", "rot_z"])
                    plt.xlabel("Timesteps")
                    plt.ylabel("Magnitude")
                    plt.title("Motion parameters")
                    plt.savefig(output_path)
                    plt.close()
                    self.written_files.append(output_path)
            return res

    def display_original_data(self, idx):
        volume = self.get_volume_nibabel(idx)
        ov(volume.get_data())

    def trsfm_arg_eval(self, arg_to_eval):
        from torchio import Interpolation
        from torchio.transforms.preprocessing.intensity.normalization_transform import NormalizationTransform

        if isinstance(arg_to_eval, str):
            try:
                if arg_to_eval.startswith("<function"):
                    arg_to_eval = arg_to_eval.split()[1]
                return eval(arg_to_eval)

            except NameError:
                return arg_to_eval
        return arg_to_eval

    def get_transformations(self, idx):
            from torchio.transforms import compose_from_history, Compose
            import torchio.transforms

            row = self.get_row(idx)
            trsfms_order = row["transfo_order"].split("_")
            trsfm_list = []
            trsfm_seeds = []
            for trsfm_name in trsfms_order:
                if trsfm_name not in ["OneOf"]:
                    trsfm_history = json.loads(row["T_"+trsfm_name])
                    trsfm_seed = trsfm_history["seed"]
                    trsfm_seeds.append(trsfm_seed)
                    del trsfm_history["seed"]
                    trsfm = custom_import({"module": "torchio.transforms", "name": trsfm_name})
                    init_args = inspect.getfullargspec(trsfm.__init__).args

                    hist_kwargs_init = {hist_key: self.trsfm_arg_eval(hist_val)
                                        for hist_key, hist_val in trsfm_history.items()
                                        if hist_key in init_args and hist_key not in ['metrics', 'fitpars', "read_func"]}

                    trsfm = trsfm(**hist_kwargs_init)
                    trsfm_list.append(trsfm)
            trsfm_composition = Compose(trsfm_list)
            return trsfm_composition, trsfm_seeds
    """
    def extract_motion_metrics(self):
        idx_motion = self.df_data[~self.df_data["T_RandomMotionFromTimeCourse"].isnull()].index.to_list()
        motion_metrics = defaultdict(list)
        for idx in idx_motion:
            tio_data = self.get_volume_torchio(idx, return_orig=True)
            trsfm_composition, seeds = self.get_transformations(idx)
            tio_data = trsfm_composition(tio_data, seeds)
            del tio_data
            for tr in trsfm_composition.transform.transforms:
                if isinstance(tr, torchio.RandomMotionFromTimeCourse):
                    motion_params = tr.parameters_motion
                    for metric_key, metric_value in motion_params.items():
                        motion_metrics[metric_key].append(metric_value)

        df_motion = pd.DataFrame.from_dict(motion_metrics)
        df_motion.index = idx_motion
        self.df_data = self.df_data.join(df_motion)
        self.df_data.to_csv(self.csv_path)
        return df_motion

    def extract_noise_metrics(self):
        idx_noise = self.df_data[~self.df_data["T_RandomNoise"].isnull()].index.to_list()
        noise_metrics = defaultdict(list)
        for idx in idx_noise:
            tio_data = self.get_volume_torchio(idx, return_orig=True)
            trsfm_composition, seeds = self.get_transformations(idx)
            tio_data = trsfm_composition(tio_data, seeds)
            del tio_data
            for tr in trsfm_composition.transform.transforms:
                if isinstance(tr, torchio.RandomNoise):
                    mean, std = tr.mean, tr.std
                    noise_metrics["noise_mean"].append(mean)
                    noise_metrics["noise_std"].append(std)
        df_noise = pd.DataFrame.from_dict(noise_metrics)
        df_noise.index = idx_noise
        self.df_data = self.df_data.join(df_noise)
        self.df_data.to_csv(self.csv_path)
        return df_noise

    def extract_spike_metrics(self):
        idx_spike = self.df_data[~self.df_data["T_RandomSpike"].isnull()].index.to_list()
        spike_metrics = defaultdict(list)
        for idx in idx_spike:
            tio_data = self.get_volume_torchio(idx, return_orig=True)
            trsfm_composition, seeds = self.get_transformations(idx)
            tio_data = trsfm_composition(tio_data, seeds)
            del tio_data
            for tr in trsfm_composition.transform.transforms:
                if isinstance(tr, torchio.RandomSpike):
                    spike_pos, spike_intensity = tr.spikes_positions_param, tr.intensity_param
                    spike_metrics["spike_pos"].append(spike_pos)
                    spike_metrics["spike_intensity"].append(spike_intensity)
        df_spike = pd.DataFrame.from_dict(spike_metrics)
        df_spike.index = idx_spike
        self.df_data = self.df_data.join(df_spike)
        self.df_data.to_csv(self.csv_path)
        return df_spike

    def extract_bias_metric(self):
        idx_bias = self.df_data[~self.df_data["T_RandomBiasField"].isnull()].index.to_list()
        bias_metrics = defaultdict(list)
        for idx in idx_bias:
            tio_data = self.get_volume_torchio(idx, return_orig=True)
            trsfm_composition, seeds = self.get_transformations(idx)
            tio_data = trsfm_composition(tio_data, seeds)
            del tio_data
            for tr in trsfm_composition.transform.transforms:
                if isinstance(tr, torchio.RandomBiasField):
                    bias_coefs = tr.coefficients
                    bias_metrics["bias_coefs"].append(bias_coefs)
        df_bias = pd.DataFrame.from_dict(bias_metrics)
        df_bias.index = idx_bias
        self.df_data = self.df_data.join(df_bias)
        self.df_data.to_csv(self.csv_path)
        return df_bias
    """
    def extract_from_history(self, col, key, save_csv=False, col_name=None):
        data_col = self.df_data[~self.df_data[col].isnull()][col]
        dict_data = data_col.apply(lambda x: json.loads(x)[key])
        if save_csv:
            if not col_name:
                col_name = key
            self.df_data[col_name] = dict_data
            self.df_data.to_csv(self.csv_path)
        return dict_data

    def check_dash(self):
        if not self.dash_app:
            self.dash_app = dash.Dash()

    def clean_tmp_dir(self):
        for f in self.written_files:
            os.remove(f)

    def correlation(self, col_x, col_y):
        filtered_df = self.df_data[~self.df_data[col_x].isnull() & ~self.df_data[col_y].isnull()]
        return filtered_df[col_y].corr(filtered_df[col_x])

    def plot_hist(self, data, save=None):
        if isinstance(data, nb.Nifti1Image):
            data = data.get_fdata().reshape(-1)
        elif isinstance(data, torch.Tensor):
            data = data.flatten().numpy()
        n, bins, patches = plt.hist(data, bins=256, range=(1, data.max()), facecolor='red', alpha=0.75,
                                    histtype='step')
        if save:
            plt.savefig(save)
        plt.close()

    def scatter(self, col_x, col_y, renderer="browser", color=None, **kwargs):
        fig = go.Figure()
        filtered_df = self.df_data[~self.df_data[col_x].isnull() & ~self.df_data[col_y].isnull()]
        if not color or color not in self.df_data.columns:
            fig.add_trace(go.Scatter(x=filtered_df[col_x], y=filtered_df[col_y],
                                     hovertext=filtered_df["image_filename"], text=filtered_df.index.to_numpy(),
                                     mode="markers", **kwargs))
        else:
            categories = filtered_df[color].unique()
            traces = []
            for idx, cat in enumerate(categories):
                cat_data = filtered_df[filtered_df[color] == cat]
                traces.append(go.Scatter(x=cat_data[col_x], y=cat_data[col_y], marker_symbol=idx,
                                         hovertext=cat_data["image_filename"], text=cat_data.index.to_numpy(),
                                         mode="markers", name=cat, **kwargs))
            fig.add_traces(traces)
        fig.update_layout(xaxis_title=col_x,
                          yaxis_title=col_y,
                          legend=dict(
                              orientation="h",
                              yanchor="bottom",
                              y=1.02,
                              xanchor="right",
                              x=1
                          )
                          )
        self.check_dash()
        self.dash_app.layout = html.Div(children=[
            html.H1(children='CSV MRI Scatter Plot'),

            html.Div(children='''
                Plot from {}
            '''.format(self.csv_path)),

            dcc.Graph(
                id='scatter-plot',
                figure=fig
                ),
            html.Div(id='output-click'),
            ])

        @self.dash_app.callback(
            [Output('output-click', 'children'),],
            [Input('scatter-plot', 'clickData'),],
        )
        def display_click_data(clickData):
            path = clickData["points"][0]["hovertext"]
            idx = clickData["points"][0]["text"]
            out_path = opj(self.out_tmp, str(idx) + ".nii")
            if not os.path.exists(out_path):
                transformed = self.get_volume_torchio(idx)["volume"]
                data, affine = transformed['data'].squeeze().numpy(), transformed["affine"]
                nib_volume = nb.Nifti1Image(data, affine)
                nib_volume.to_filename(out_path)
                self.written_files.append(out_path)
                self.plot_hist(nib_volume, save=opj(self.out_tmp, str(idx) + "_hist.png"))
            if path:
                os.system("mrviewv " + out_path)
            return "Viewing: {}".format(path)

        self.dash_app.run_server(debug=False)