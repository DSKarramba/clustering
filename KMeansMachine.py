from __future__ import division, print_function
import geojson as json
import time
import numpy as np
import os
from geographiclib.geodesic import Geodesic

from routelib import route
from ClusteringMachine import ClusteringMachine

from multiprocessing.dummy import Pool as ThreadPool
THREADS = 4
POOL = ThreadPool(processes=THREADS)
QUIET = False

def asyncWorker(iterator, func, data=None):
    thread_list = []
    result = []
    for item in iterator:
        # create job for function
        thread = POOL.apply_async(func, (item, data))
        # add thread in list
        thread_list.append(thread)
    for thread in thread_list:
        # get result of job
        result.append(thread.get())
    return result

def dump(data, filename):
    try:
        with open(filename, 'w') as file_:
            json.dump(data, file_)
    except IOError as e:
        print('{}'.format(e))

class KMeans():
    """ K-Means clustering.

    Attributes
    ----------
    maxIter : int
        Maximum iteration number. After reaching it, clustering is
        considered as completed.
    clusterCenters : array, [n_clusters, n_dimensions + 1]
        Centers of clusters.
    labels : array, [n_points]
        Labels of points.

    Parameters
    ----------
    maxIter : int
        Set maximum iteration number.
    """
    maxIter = None
    clusterCenters = None
    labels = None
    population = None
    log = False
    continue_ = False
    route = None
    icntr = 0

    def __init__(self, maxIter, log, start, stations, map_):
        self.maxIter = maxIter
        self.log = log
        self.continue_ = start
        self.stations = stations
        self.route = route()
        self.map_ = map_

    def dist(self, a, b, metric):
        """ Calculate distance between two points.

        Parameters
        ----------
        a : array, [n_dimensions]
            First point.
        b : array, [n_dimensions]
            Second point.

        Returns
        -------
        r : float
            Distance between points.
        """
        if metric == 'route':
            r = self.route.route_distance(a, b)
        elif metric == 'euclid':
            r = np.sqrt((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2)
        elif metric == 'surface':
            r = Geodesic.WGS84.Inverse(a[0], a[1], b[0], b[1])['s12']
        else:
            raise ValueError('Unknown metric: {}'.format(metric))
        self.icntr += 1
        if not QUIET:
            text = '      progress: {:.2f}k / {:.2f}k'.format(self.icntr / 1000, self.x_len * self.c_len / 1000)
            digits = len(text)
            delete = '\r' * digits
            print('{0}{1}'.format(delete, text), end='')
        return r

    def stop(self, iter, old, new, lold, lnew):
        """ Check whenever clustering needs to be stopped.

        Parameters
        ----------
        iter : int
            Number of current iteration.
        old : array, [n_clusters, n_dimensions + 1]
            Centers of clusters on previous iteration.
        new : array, [n_clusters, n_dimensions + 1]
            Centers of clusters on current iteration.

        Returns
        -------
        stop : boolean
            If true, clustering is completed.
        """
        if iter >= self.maxIter:
            return True
        return np.array_equal(old, new) or np.array_equal(lold, lnew)

    def cloop(self, i, j):
        return (self.dist(self.X[i], self.C[j], self.metric), j)

    def xloop(self, i, _=None):
        # calculate distance between point and all the clusters centers
        D = list(map(lambda j: self.cloop(i, j), range(self.c_len)))
        # D = list(POOL.map(lambda j: self.cloop(i, j), range(self.c_len)))
        # sort distances ascending
        D.sort(key=lambda x: x[0])
        # pick number of cluster, which center has the smallest
        # distance to point
        m = D[0][1]
        # set label of point
        self.L[i] = self.C[m][2]
        self.P[m] += 1
        self.A[m] = np.append(self.A[m], [self.X[i]], axis=0)

    def fit(self, X, C, metric):
        """ Perform clustering.

        Parameters
        ----------
        X : array, [n_points, n_dimensions]
            Coordinates of points.
        C : array, [n_clusters, n_dimensions + 1]
            Centers of clusters.
        """
        # set initial parameters
        iteration = 0
        c_old = None
        l_old = None
        # get length of lists
        self.c_len = len(C)
        self.x_len = len(X)
        if not QUIET:
            print('Now {} points will be clustering to {} clusters'.format(self.x_len, self.c_len))
            print('Threads count: {}; log: {}'.format(THREADS, self.log))

        self.L = np.empty([self.x_len])
        self.C = C
        self.X = X
        self.P = None
        self.A = None
        self.metric = metric
        self.sleeping = 0

        if self.metric == 'route' or self.stations:
            self.route.start(loud=self.map_[0], map_=self.map_[1])
            self.sleeping += self.route.sleep
        # while clustering isn't completed
        while not self.stop(iteration, c_old, self.C, l_old, self.L):
            time_start = time.time()
            # reset population in clusters
            self.P = np.zeros([self.c_len])
            # show iteration number
            if not QUIET:
                print('Iteration {}'.format(iteration + 1))
            # create empty python array
            # each item will contain all the points belongs to specific cluster
            self.A = [np.empty([0, 2]) for i in range(self.c_len)]
            # for each point
            if not QUIET:
                print('  assigning points')
            l_old = np.array(self.L)
            if not self.continue_:
                res = asyncWorker(range(self.x_len), self.xloop)
                # res = list(POOL.map(self.xloop, range(self.x_len)))
                # res = list(map(self.xloop, range(self.x_len)))
                # equate the previous and current centers of clusters
                c_old = self.C
                if self.log:
                    if self.log is not True:
                        path = '{}'.format(self.log)
                    else:
                        path = 'km_{}'.format(self.metric[:2])
                    if path == '':
                        path = '.'
                    else:
                        if not (os.path.exists(path)):
                             os.makedirs(path)
                    cc = self.C
                    cc = list(map(lambda x, y: (np.append(x, y)).tolist(), cc, self.P))
                    filename = '{}/{}_centers_{}.js'.format(path, self.metric[0], iteration + 1)
                    dump(cc, filename)

                    xc = self.X
                    xc = list(map(lambda x, y: (np.append(x, y)).tolist(), xc, self.L))
                    filename = '{}/{}_points_{}.js'.format(path, self.metric[0], iteration + 1)
                    dump(xc, filename)
            else:
                self.L = np.array([])
                for i in json.load(open(self.continue_)):
                    self.L = np.append(self.L, i[2])
                    self.A[int(i[2])] = np.append(self.A[int(i[2])], [[i[0], i[1]]], axis=0)
                self.continue_ = False

            # array for calculated centers of clusters
            mu = np.empty([self.c_len, 3], dtype='object')

            if not QUIET:
                print('\n  calculating new centers')
            # for each cluster
            i = 0
            while i < self.c_len:
                # if it contains points
                if self.P[i] != 0:
                    # calculate center of cluster
                    k = np.array(np.round(np.mean(self.A[i], axis=0), decimals=5), dtype='object')
                    mu[i] = np.append(k, i)
                else:
                    d = np.round(self.C[i][:2].astype(np.double), decimals=5)
                    mu[i] = np.append(d.astype(np.object), i)
                i += 1
            if self.stations:
                if not QUIET:
                    print('  locating centers on roadmap')
                for c in range(self.c_len):
                    if not QUIET:
                        text = '      progress: {} / {}'.format(c + 1, self.c_len)
                        digits = len(text)
                        delete = '\r' * digits
                        print('{0}{1}'.format(delete, text), end='')
                    new = self.route.locate(mu[c][:2])
                    mu[c][0], mu[c][1] = new[0], new[1]
            if not QUIET:
                print('  replacing old centers with new')
            # equate current centroids to calculated
            self.C = mu
            # increment iteration counter
            iteration += 1
            if not QUIET:
                print('  iteration end: {:.2f}k distance calculations'.format(self.icntr / 1000))
                iter_time = time.time() - time_start
                if iter_time > 86400:
                    iter_time = '{:.4f} days'.format(iter_time / 86400)
                elif iter_time > 3600:
                    iter_time = '{:.4f} hours'.format(iter_time / 3600)
                elif iter_time > 60:
                    iter_time = '{:.4f} minutes'.format(iter_time / 60)
                else:
                    iter_time = '{:.4f} seconds'.format(iter_time)
                print(' ' * 17 + '{}'.format(iter_time))
            self.icntr = 0
        # record results
        self.clusterCenters = self.C
        self.labels = self.L
        self.population = self.P
        if self.metric == 'route' or self.stations:
            self.route.stop()

class KMeansClusteringMachine(ClusteringMachine):
    """ A derived class from ClusteringMachine.

    Performs clustering with using K-Means algorithm.

    Parameters
    ----------
    X : array, [n_points, n_dimensions]
        Coordinates of points.
    init : array, [n_points, n_dimensions + 1]
        Initial clusters' distribution.
    maxIter : int, default 100
        Set maximum iteration number.
    log : boolean / string, default False
        If set to not false, clusters' centers and points will be
        recorded on each iteration.
    threadCound : positive int, default 4

    start: boolean / array
    """

    def __init__(self, X, init, maxIter=100, log=False, threadCound=4,
                 start=False, stations=False, quiet=False, map_=(False, '')):
        global POOL
        global THREADS
        global QUIET
        if threadCound < 1:
            THREADS = 1
        else:
            THREADS = threadCound
        POOL = ThreadPool(processes=THREADS)
        QUIET = quiet

        self.X = X
        self.clusterCenters = init
        self.clusterInstance = KMeans(maxIter=maxIter, log=log, start=start,
                                       stations=stations, map_=map_)

    def fit(self, metric='route'):
        """ Perform clustering.

        """
        t_start = time.time()
        # perform clustering
        self.clusterInstance.fit(self.X, self.clusterCenters, metric)
        # calculate time
        self.fitTime = time.time() - t_start - self.clusterInstance.sleeping
        if self.fitTime > 86400:
            self.fitTime = '{:.4f} days'.format(self.fitTime / 86400)
        elif self.fitTime > 3600:
            self.fitTime = '{:.4f} hours'.format(self.fitTime / 3600)
        elif self.fitTime > 60:
            self.fitTime = '{:.4f} minutes'.format(self.fitTime / 60)
        else:
            self.fitTime = '{:.4f} seconds'.format(self.fitTime)
        # get points labels
        self.labels = self.clusterInstance.labels
        # get clusters population
        self.population = self.clusterInstance.population
        # get cluster centers
        self.clusterCenters = self.clusterInstance.clusterCenters
        # get clusters number
        self.numCluster = len(np.unique(self.labels))
