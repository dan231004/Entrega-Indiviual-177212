#!/usr/bin/env python3

import csv
import math
import os
from datetime import datetime

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from turtlesim.msg import Pose


class TurtleGoToGoalMetrics(Node):
    def __init__(self):
        super().__init__('turtle_go_to_goal_metrics')

        # =========================
        # Parámetros configurables
        # =========================
        self.goal_x = float(self.declare_parameter('goal_x', 8.0).value)
        self.goal_y = float(self.declare_parameter('goal_y', 8.0).value)

        self.k_linear = float(self.declare_parameter('k_linear', 1.5).value)
        self.k_angular = float(self.declare_parameter('k_angular', 4.0).value)

        self.tolerance = float(self.declare_parameter('tolerance', 0.10).value)
        self.max_linear_speed = float(self.declare_parameter('max_linear_speed', 2.0).value)
        self.max_angular_speed = float(self.declare_parameter('max_angular_speed', 2.0).value)

        # Si el error angular es grande, se reduce la velocidad lineal para evitar curvas bruscas.
        self.use_alignment_slowdown = bool(
            self.declare_parameter('use_alignment_slowdown', True).value
        )

        # Umbral para contar oscilaciones.
        # Se cuenta una oscilación cuando cambia el signo de la velocidad angular
        # de forma suficientemente marcada.
        self.oscillation_threshold = float(
            self.declare_parameter('oscillation_threshold', 0.25).value
        )

        self.case_name = str(self.declare_parameter('case_name', 'A').value)
        self.log_dir = str(self.declare_parameter('log_dir', 'metrics_logs').value)

        os.makedirs(self.log_dir, exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.csv_path = os.path.join(
            self.log_dir,
            f'turtle_metrics_case_{self.case_name}_{timestamp}.csv'
        )
        self.summary_path = os.path.join(
            self.log_dir,
            f'turtle_summary_case_{self.case_name}_{timestamp}.csv'
        )

        # =========================
        # ROS 2: publisher/subscriber
        # =========================
        self.publisher_ = self.create_publisher(Twist, '/turtle1/cmd_vel', 10)

        self.subscription = self.create_subscription(
            Pose,
            '/turtle1/pose',
            self.pose_callback,
            10
        )

        self.timer = self.create_timer(0.1, self.control_loop)  # 10 Hz

        # =========================
        # Variables de estado
        # =========================
        self.current_pose = None
        self.previous_pose = None

        self.start_time = None
        self.finished = False

        # =========================
        # Métricas
        # =========================
        self.initial_error = None
        self.final_error = None
        self.arrival_time = 0.0

        self.total_distance = 0.0

        self.max_error = 0.0
        self.error_sum = 0.0
        self.error_samples = 0

        self.oscillations = 0
        self.previous_angular_sign = 0

        self.max_linear_applied = 0.0
        self.max_angular_applied = 0.0

        self.rows = []

        self.get_logger().info('Nodo turtle_go_to_goal_metrics iniciado.')
        self.get_logger().info(
            f'Caso {self.case_name} | '
            f'Meta=({self.goal_x:.2f}, {self.goal_y:.2f}) | '
            f'k_linear={self.k_linear:.2f} | '
            f'k_angular={self.k_angular:.2f}'
        )

    def pose_callback(self, msg):
        self.current_pose = msg

        if self.finished:
            return

        # Cálculo aproximado de distancia recorrida por integración de segmentos.
        if self.previous_pose is not None:
            dx = msg.x - self.previous_pose.x
            dy = msg.y - self.previous_pose.y
            step_distance = math.sqrt(dx**2 + dy**2)

            # Filtro simple para evitar sumar saltos muy grandes si se reinicia la tortuga.
            if step_distance < 1.0:
                self.total_distance += step_distance

        self.previous_pose = msg

    def control_loop(self):
        if self.current_pose is None or self.finished:
            return

        now = self.get_clock().now().nanoseconds / 1e9

        if self.start_time is None:
            self.start_time = now

        elapsed_time = now - self.start_time

        # =========================
        # Pose actual
        # =========================
        x = self.current_pose.x
        y = self.current_pose.y
        theta = self.current_pose.theta

        # =========================
        # Errores
        # =========================
        error_x = self.goal_x - x
        error_y = self.goal_y - y

        distance_error = math.sqrt(error_x**2 + error_y**2)
        angle_to_goal = math.atan2(error_y, error_x)

        angle_error = angle_to_goal - theta
        angle_error = math.atan2(math.sin(angle_error), math.cos(angle_error))

        # Inicializar error inicial
        if self.initial_error is None:
            self.initial_error = distance_error
            self.max_error = distance_error

        # Actualizar métricas de error
        self.max_error = max(self.max_error, distance_error)
        self.error_sum += distance_error
        self.error_samples += 1

        # =========================
        # Condición de parada
        # =========================
        if distance_error < self.tolerance:
            stop_msg = Twist()
            self.publisher_.publish(stop_msg)

            self.final_error = distance_error
            self.arrival_time = elapsed_time
            self.finished = True

            # Registrar una última muestra con velocidad cero
            self.save_sample(
                elapsed_time,
                x,
                y,
                theta,
                distance_error,
                angle_error,
                0.0,
                0.0
            )

            self.print_metrics()
            self.save_files()
            return

        # =========================
        # Ley de control proporcional
        # =========================
        linear_cmd = self.k_linear * distance_error
        angular_cmd = self.k_angular * angle_error

        # Reducción de velocidad lineal cuando la tortuga está muy desalineada.
        # Esto ayuda a disminuir oscilaciones y movimientos innecesarios.
        if self.use_alignment_slowdown:
            alignment_factor = max(0.0, math.cos(angle_error))
            linear_cmd *= alignment_factor

        # Limitar velocidades
        linear_cmd = max(0.0, min(linear_cmd, self.max_linear_speed))
        angular_cmd = max(-self.max_angular_speed, min(angular_cmd, self.max_angular_speed))

        # Detectar oscilaciones por cambios de signo en velocidad angular
        self.detect_oscillation(angular_cmd)

        # Actualizar máximos
        self.max_linear_applied = max(self.max_linear_applied, abs(linear_cmd))
        self.max_angular_applied = max(self.max_angular_applied, abs(angular_cmd))

        # Publicar velocidades
        msg = Twist()
        msg.linear.x = linear_cmd
        msg.angular.z = angular_cmd
        self.publisher_.publish(msg)

        # Guardar muestra para análisis experimental
        self.save_sample(
            elapsed_time,
            x,
            y,
            theta,
            distance_error,
            angle_error,
            linear_cmd,
            angular_cmd
        )

        self.get_logger().info(
            f'Caso {self.case_name} | '
            f't={elapsed_time:.2f}s | '
            f'pos=({x:.2f}, {y:.2f}) | '
            f'error={distance_error:.3f} | '
            f'angle_error={angle_error:.3f} | '
            f'v={linear_cmd:.3f} | '
            f'w={angular_cmd:.3f}'
        )

    def detect_oscillation(self, angular_cmd):
        if abs(angular_cmd) < self.oscillation_threshold:
            return

        current_sign = 1 if angular_cmd > 0 else -1

        if self.previous_angular_sign != 0 and current_sign != self.previous_angular_sign:
            self.oscillations += 1

        self.previous_angular_sign = current_sign

    def save_sample(self, t, x, y, theta, distance_error, angle_error, linear_x, angular_z):
        self.rows.append({
            'case': self.case_name,
            'time_s': t,
            'x': x,
            'y': y,
            'theta': theta,
            'distance_error': distance_error,
            'angle_error': angle_error,
            'linear_x': linear_x,
            'angular_z': angular_z,
            'total_distance': self.total_distance,
            'oscillations': self.oscillations,
            'k_linear': self.k_linear,
            'k_angular': self.k_angular
        })

    def get_average_error(self):
        if self.error_samples == 0:
            return 0.0
        return self.error_sum / self.error_samples

    def print_metrics(self):
        self.get_logger().info('Meta alcanzada.')
        self.get_logger().info('Métricas de desempeño:')
        self.get_logger().info(f'Error inicial: {self.initial_error:.4f}')
        self.get_logger().info(f'Error final: {self.final_error:.4f}')
        self.get_logger().info(f'Tiempo de llegada: {self.arrival_time:.4f} s')
        self.get_logger().info(f'Distancia recorrida: {self.total_distance:.4f}')
        self.get_logger().info(f'Error máximo: {self.max_error:.4f}')
        self.get_logger().info(f'Error promedio: {self.get_average_error():.4f}')
        self.get_logger().info(f'Oscilaciones detectadas: {self.oscillations}')
        self.get_logger().info(f'Velocidad lineal máxima: {self.max_linear_applied:.4f}')
        self.get_logger().info(f'Velocidad angular máxima: {self.max_angular_applied:.4f}')
        self.get_logger().info(f'CSV de trayectoria: {self.csv_path}')
        self.get_logger().info(f'CSV de resumen: {self.summary_path}')

    def save_files(self):
        if len(self.rows) == 0:
            return

        # Guardar trayectoria completa
        with open(self.csv_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=self.rows[0].keys())
            writer.writeheader()
            writer.writerows(self.rows)

        # Guardar resumen de métricas
        summary_rows = [
            ['case', self.case_name],
            ['k_linear', self.k_linear],
            ['k_angular', self.k_angular],
            ['goal_x', self.goal_x],
            ['goal_y', self.goal_y],
            ['tolerance', self.tolerance],
            ['error_initial', self.initial_error],
            ['error_final', self.final_error],
            ['arrival_time_s', self.arrival_time],
            ['total_distance', self.total_distance],
            ['error_max', self.max_error],
            ['error_average', self.get_average_error()],
            ['oscillations', self.oscillations],
            ['max_linear_speed_applied', self.max_linear_applied],
            ['max_angular_speed_applied', self.max_angular_applied],
        ]

        with open(self.summary_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['metric', 'value'])
            writer.writerows(summary_rows)


def main(args=None):
    rclpy.init(args=args)

    node = TurtleGoToGoalMetrics()

    try:
        # Se usa spin_once para que el programa termine automáticamente
        # cuando la meta sea alcanzada.
        while rclpy.ok() and not node.finished:
            rclpy.spin_once(node, timeout_sec=0.1)

    except KeyboardInterrupt:
        stop_msg = Twist()
        node.publisher_.publish(stop_msg)
        node.get_logger().info('Ejecución interrumpida por el usuario.')

    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
