import numpy as np

from core.runtime import opts
from core.material import MaterialModel
from utils.data_containers import Parameters
from utils.constants import ROOT2, ROOT3, TOOR2, TOOR3, I6


class PyPlastic(MaterialModel):

    def __init__(self):
        self.name = "pyplastic"
        self.param_names = ["K",    # Linear elastic bulk modulus
                            "G",    # Linear elastic shear modulus
                            "A1",   # Intersection of the yield surface with the
                                    #   sqrt(J2) axis (pure shear).
                                    #     sqrt(J2) = r / sqrt(2); r = sqrt(2*J2)
                                    #     sqrt(J2) = q / sqrt(3); q = sqrt(3*J2)
                           "A4"]   # Pressure dependence term.
                                   #   A4 = -d(sqrt(J2)) / d(I1)
                                   #         always positive

    def setup(self):
        """Set up the plastic material

        """
        # Check inputs
        if opts.mimic == 'elastic':
            logger.write("model '{0}' mimicing '{1}'".format(
                self.name, self.params.modelname))
            K = self.params["K"]
            G = self.params["G"]
            A1 = 1.0e99
            A4 = 0.0
        elif opts.mimic == 'vonmises':
            self.logger.write("model '{0}' mimicing "
                              "'{1}'".format(self.name, opts.mimic))
            K = self.params["K"]
            G = self.params["G"]
            A1 = self.params["Y0"] * TOOR3
            A4 = 0.0
            if self.params["H"] != 0.0:
                self.logger.error("model {0} cannot mimic {1} with "
                                  "hardening".format(self.name, opts.mimic))
        else:
            # default
            K = self.params["K"]
            G = self.params["G"]
            A1 = self.params["A1"]
            A4 = self.params["A4"]
            if A1 == 0.0:
                A1 = 1.0e99

        # Check the input parameters
        errors = 0
        if K <= 0.0:
            errors += 1
            self.logger.error("Bulk modulus K must be positive")
        if G <= 0.0:
            errors += 1
            self.logger.error("Shear modulus G must be positive")
        nu = (3.0 * K - 2.0 * G) / (6.0 * K + 2.0 * G)
        if nu > 0.5:
            errors += 1
            self.logger.error("Poisson's ratio > .5")
        if nu < -1.0:
            errors += 1
            self.logger.error("Poisson's ratio < -1.")
        if nu < 0.0:
            self.logger.write("#---- WARNING: negative Poisson's ratio")
        if A1 <= 0.0:
            errors += 1
            self.logger.error("A1 must be positive nonzero")
        if A4 <= 0.0:
            errors += 1
            self.logger.error("A4 must be positive nonzero")
        if errors:
            self.logger.error("stopping due to previous errors")

        # Save the new parameters
        newparams = [K, G, A1, A4]
        self.params = Parameters(self.parameter_names, newparams)

        self.bulk_modulus = self.params["K"]
        self.shear_modulus = self.params["G"]

        # Register State Variables
        self.sv_names = ["EP_XX", "EP_YY", "EP_ZZ", "EP_XY", "EP_XZ", "EP_YZ",
                         "I1", "ROOTJ2", "YROOTJ2", "ISPLASTIC"]
        sv_values = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        self.register_xtra_variables(self.sv_names, sv_values)

    def update_state(self, time, dtime, temp, dtemp, energy, rho, F0, F,
        stran, d, elec_field, user_field, stress, xtra, **kwargs):
        """Compute updated stress given strain increment

        Parameters
        ----------
        dtime : float
            Time step

        d : array_like
            Deformation rate

        stress : array_like
            Stress at beginning of step

        xtra : array_like
            Extra variables

        Returns
        -------
        S : array_like
            Updated stress

        xtra : array_like
            Updated extra variables

        """
        sigsave = np.copy(stress)
        # Define helper functions and unload params/state vars
        A1 = self.params["A1"]
        A4 = self.params["A4"]
        idx = lambda x: self.sv_names.index(x.upper())
        ep = xtra[idx('EP_XX'):idx('EP_YZ')+1]

        # Compute the trial stress and invariants
        stress = stress + self.dot_with_elastic_stiffness(d * dtime)
        i1 = self.i1(stress)
        rootj2 = self.rootj2(stress)
        if rootj2 - (A1 - A4 * i1) <= 0.0:
            xtra[idx('ISPLASTIC')] = 0.0
        else:
            xtra[idx('ISPLASTIC')] = 1.0

            s = self.dev(stress)
            N = ROOT2 * A4 * I6 + s / self.tensor_mag(s)
            N = N / np.sqrt(6.0 * A4 ** 2 + 1.0)
            P = self.dot_with_elastic_stiffness(N)

            # 1) Check if linear drucker-prager
            # 2) Check if trial stress is beyond the vertex
            # 3) Check if trial stress is in the vertex
            if (A4 != 0.0 and
                    i1 > A1 / A4 and
                    rootj2 / (i1 - A1 / A4) < self.rootj2(P) / self.i1(P)):
                dstress = stress - A1 / A4 / 3.0 * I6
                # convert all of the extra strain into plastic strain
                ep += self.iso(dstress) / (3.0 * self.params["K"])
                ep += self.dev(dstress) / (2.0 * self.params["G"])
                stress = A1 / A4 / 3.0 * I6
            else:
                # not in vertex; do regular return
                lamb = ((rootj2 - A1 + A4 * i1) / (A4 * self.i1(P)
                        + self.rootj2(P)))
                stress = stress - lamb * P
                ep += lamb * N

            # Save the updated plastic strain
            xtra[idx('EP_XX'):idx('EP_YZ')+1] = ep

        xtra[idx('I1')] = self.i1(stress)
        xtra[idx('ROOTJ2')] = self.rootj2(stress)
        xtra[idx('YROOTJ2')] = A1 - A4 * self.i1(stress)

        return stress, xtra, self.constant_jacobian

    def dot_with_elastic_stiffness(self, A):
        return (3.0 * self.params["K"] * self.iso(A) +
                2.0 * self.params["G"] * self.dev(A))

    def tensor_mag(self, A):
        return np.sqrt(np.dot(A[:3], A[:3]) + 2.0 * np.dot(A[3:], A[3:]))

    def iso(self, sig):
        return sig[:3].sum() / 3.0 * I6

    def dev(self, sig):
        return sig - self.iso(sig)

    def rootj2(self, sig):
        s = self.dev(sig)
        return self.tensor_mag(s) * TOOR2

    def i1(self, sig):
        return np.sum(sig[:3])
