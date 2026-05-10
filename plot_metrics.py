#!/usr/bin/env python3

import csv
import glob
import os

import matplotlib.pyplot as plt


LOG_DIR = 'metrics_logs'
IMG_DIR = 'images'


def read_trajectory_csv(path):
    data = {
        'case': [],
        'time_s': [],
        'distance_error': [],
        'linear_x': [],
        'angular_z': [],
        'total_distance': [],
        'oscillations': []
    }

    with open(path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            data['case'].append(row['case'])
            data['time_s'].append(float(row['time_s']))
            data['distance_error'].append(float(row['distance_error']))
            data['linear_x'].append(float(row['linear_x']))
            data['angular_z'].append(float(row['angular_z']))
            data['total_distance'].append(float(row['total_distance']))
            data['oscillations'].append(int(float(row['oscillations'])))

    return data


def plot_metric(files, metric_key, ylabel, output_name):
    plt.figure()

    for file in files:
        data = read_trajectory_csv(file)
        case = data['case'][0] if data['case'] else os.path.basename(file)
        plt.plot(data['time_s'], data[metric_key], label=f'Caso {case}')

    plt.xlabel('Tiempo [s]')
    plt.ylabel(ylabel)
    plt.title(ylabel + ' vs tiempo')
    plt.grid(True)
    plt.legend()
    plt.tight_layout()

    output_path = os.path.join(IMG_DIR, output_name)
    plt.savefig(output_path, dpi=300)
    print(f'Gráfica guardada: {output_path}')


def build_comparison(files):
    rows = []

    for file in files:
        data = read_trajectory_csv(file)

        if not data['time_s']:
            continue

        case = data['case'][0]
        time_final = data['time_s'][-1]
        error_final = data['distance_error'][-1]
        distance_final = data['total_distance'][-1]
        oscillations_final = data['oscillations'][-1]

        rows.append({
            'case': case,
            'time_s': time_final,
            'error_final': error_final,
            'total_distance': distance_final,
            'oscillations': oscillations_final
        })

    output_csv = os.path.join(LOG_DIR, 'comparison_metrics.csv')
    with open(output_csv, 'w', newline='') as f:
        writer = csv.DictWriter(
            f,
            fieldnames=['case', 'time_s', 'error_final', 'total_distance', 'oscillations']
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f'Tabla comparativa guardada: {output_csv}')

    # Gráfica sencilla de comparación usando tiempo final.
    plt.figure()
    cases = [r['case'] for r in rows]
    times = [r['time_s'] for r in rows]

    plt.bar(cases, times)
    plt.xlabel('Caso')
    plt.ylabel('Tiempo de llegada [s]')
    plt.title('Comparación de tiempo de llegada')
    plt.grid(True)
    plt.tight_layout()

    output_path = os.path.join(IMG_DIR, 'comparison_time.png')
    plt.savefig(output_path, dpi=300)
    print(f'Gráfica guardada: {output_path}')


def main():
    os.makedirs(IMG_DIR, exist_ok=True)

    files = sorted(glob.glob(os.path.join(LOG_DIR, 'turtle_metrics_case_*.csv')))

    if not files:
        print('No se encontraron archivos CSV en metrics_logs/.')
        print('Primero ejecuta turtle_go_to_goal_metrics.py al menos una vez.')
        return

    plot_metric(files, 'distance_error', 'Error de distancia', 'error_vs_time.png')
    plot_metric(files, 'linear_x', 'Velocidad lineal', 'linear_velocity_vs_time.png')
    plot_metric(files, 'angular_z', 'Velocidad angular', 'angular_velocity_vs_time.png')
    build_comparison(files)


if __name__ == '__main__':
    main()
