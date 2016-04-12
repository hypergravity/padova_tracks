from __future__ import print_function
import matplotlib.pylab as plt
import numpy as np
import os
import pdb
from critical_point import critical_point, Eep
from scipy.interpolate import splev, splprep
from .. import utils
from ..interpolate import Interpolator

from ..config import *

import logging
logger = logging.getLogger()


def second_derivative(xdata, inds, gt=False, s=0):
    '''
    The second derivative of d^2 xdata / d inds^2

    why inds for interpolation, not log l?
    if not using something like model number instead of log l,
    the tmin will get hidden by data with t < tmin but different
    log l. This is only a problem for very low Z.
    If I find the arg min of teff to be very close to MS_BEG it
    probably means the MS_BEG is at a lower Teff than Tmin.
    '''
    tckp, _ = splprep([inds, xdata], s=s, k=3)
    arb_arr = np.arange(0, 1, 1e-2)
    xnew, ynew = splev(arb_arr, tckp)
    # second derivative, bitches.
    ddxnew, ddynew = splev(arb_arr, tckp, der=2)
    ddyddx = ddynew/ddxnew
    # not just argmin, but must be actual min...
    try:
        if gt:
            aind = [a for a in np.argsort(ddyddx) if ddyddx[a-1] < 0][0]
        else:
            aind = [a for a in np.argsort(ddyddx) if ddyddx[a-1] > 0][0]
    except IndexError:
        return -1
    tmin_ind, _ = utils.closest_match2d(aind, inds, xdata, xnew, ynew)
    return inds[tmin_ind]

class DefineEeps(Interpolator):
    '''
    Define the stages if not simply using Sandro's defaults.

    * denotes stages defined here, otherwise, taken from Sandro's defaults.
    0 PMS_BEG*     Beginning of Pre Main Sequence
                     Replaced by first model older than age = 0.2 if Sandro's
                     PMS_BEG has age <= 0.2.
    1 PMS_MIN      Minimum of Pre Main Sequence
    2 PMS_END      End of Pre-Main Sequence
    3 MS_BEG*      Starting of the central H-burning phase
                     Replaced by Log L min after PMS_END for M > high_mass.
    4 MS_TMIN*     Calculated one of four possible ways:
                     1) First Minimum in Teff
                     2) For no minimum Teff (M>50, usually >100),
                        halfway in age between MS_BEG and MS_TO
                     3) Xc=0.30 for low-mass stars (via BaSTi)
                     4) For very low mass stars that never reach Xc=0.30
                        half the age of the universe ~= 13.7/2 Gyr
    5 MS_TO*       Maximum in Teff along the Main Sequence - Turn Off (BaSTi)
                     For very low mass stars that never reach the MSTO:
                     the age of the universe ~= 13.7 Gyr
    6 SG_MAXL*     Maximum in logL for high-mass or Xc=0.0 for low-mass stars
                     (BaSTi)
    7 RG_MINL*     Minimum in logL for high-mass or Base of the RGB for
                     low-mass stars (BaSTi)

    8 RG_BMP1      The maximum luminosity during the RGB Bump
    9 RG_BMP2      The minimum luminosity during the RGB Bump
    10 RG_TIP      Tip of the RGB from Sandro is defined in 3 ways:
                     1) If the last track model still has a YCEN val > 0.1
                        the TRGB is either the min te or the last model, which
                        ever comes first. (low masses)
                     2) If there is no YCEN left in the core at the last track
                        model, TRGB is the min TE where YCEN > 1-Z-0.1.
                     3) If there is still XCEN in the core (very low mass),
                        TRGB is the final track model point.
    11 HE_BEG*     Start quiescent central He-burning phase
                     LY Min after the TRGB, a dips as the star contracts,
                     and then ramps up.
    12 YCEN_0.550* Central abundance of He equal to 0.550
    13 YCEN_0.500* Central abundance of He equal to 0.500
    14 YCEN_0.400* Central abundance of He equal to 0.400
    15 YCEN_0.200* Central abundance of He equal to 0.200
    16 YCEN_0.100* Central abundance of He equal to 0.100
    17 YCEN_0.005* Central abundance of He equal to 0.005
    18 YCEN_0.000* Central abundance of He equal to 0.000

    19 AGB_LY1*     Helium (shell) fusion first overpowers hydrogen (shell)
                    fusion
    20 AGB_LY2*     Hydrogen wins again (before TPAGB).

    21 TPAGB        Starting of the central C-burning phase
                        or beginning of TPAGB.

    Not yet implemented, no TPAGB tracks decided:
    x When the energy produced by the CNO cycle is larger than that
    provided by the He burning during the AGB (Lcno > L3alpha)
    x The maximum luminosity before the first Thermal Pulse
    x The AGB termination
    '''
    def __init__(self):
        Interpolator.__init__(self)

    def check_for_monotonic_increase(self, track):
        if track.flag is not None:
            # issues are already documented.
            pass
        else:
            negatives = np.nonzero(np.diff(track.iptcri[track.iptcri > 0]) <= 0)[0]
            if len(negatives) > 0:
                from critical_point import Eep
                eep = Eep()
                if track.hb:
                    l = eep.eep_list_hb
                else:
                    l = eep.eep_list
                track.flag = 'eeps not monotonically increasing'
                print(track.flag)
                print(np.array(l)[negatives+1])
                import pdb; pdb.set_trace()

    def define_eep_stages(self, track, hb=False, plot_dir=None,
                          diag_plot=True, agb=False, debug=False):
        """
        Define all eeps (add as track.iptcri)

        Parameters
        ----------
        track : object
            rsp.padova_track.Track object
        hb : bool [False]
            track is an HB track
        plot_dir : str
            loction to put plots (if diag_plot)
        diag_plot : bool
            make diagnostic plots
        agb : bool
            track is an AGB track
        """
        self.debug = debug
        track.info = {}
        # initalize to zero
        [self.add_eep(track, cp, 0) for cp in self.ptcri.please_define]
        nsandro_pts = len(np.nonzero(track.sptcri != 0)[0])

        # TP-AGB tracks
        if track.agb:
            self.add_tpagb_eeps(track)

        # ZAHB tracks
        if hb:
            self.hb_eeps(track, diag_plot=diag_plot, plot_dir=plot_dir)
            return self.check_for_monotonic_increase(track)

        self.check_pms_beg(track)

        if len(track.sptcri) <= 4 or track.data[xcen][track.sptcri[4]] < .6:
            try:
                track.info['MS_BEG'] = \
                    'Sandro\'s MS_BEG but could be wrong XCEN < 0.6, %.f' % \
                    track.data[xcen][track.sptcri[4]]
            except:
                track.info['MS_BEG'] = 'Incomplete track?'
                print('incomplete track?!', track.mass)
                ind, = np.nonzero(self.ptcri.masses == track.mass)
                d
            if track.mass <= low_mass:
                self.add_ms_beg_eep(track)

        if track.mass >= high_mass:
            #print('M=%.4f is high mass' % track.mass)
            self.add_high_mass_eeps(track)
            return self.check_for_monotonic_increase(track)

        # Low mass tracks
        if len(track.sptcri) <= 6:
            # no MSTO according to Sandro
            [self.add_eep(track, cp, 0, message='No MS_TO')
             for cp in self.ptcri.please_define]
            ims_beg = track.iptcri[self.ptcri.get_ptcri_name('MS_BEG',
                                                             sandro=False)]
            ims_to, age = self.add_eep_with_age(track, 'MS_TO', max_age)
            ims_tmin, _ = self.add_eep_with_age(track, 'MS_TMIN', (age / 2.))
            # it's possible that MS_BEG occurs after max_age / 2
            # if that's the case, take the average age between ms_beg and ms_to
            if ims_tmin <= ims_beg:
                age = (track.data[age][ims_to] + track.data[age][ims_beg]) / 2.
                ims_tmin, _ = self.add_eep_with_age(track, 'MS_TMIN', age)

            return self.check_for_monotonic_increase(track)

        # Intermediate mass tracks
        self.add_ms_eeps(track)

        ihe_beg = 0
        self.add_eep(track, 'HE_BEG', ihe_beg, message='Initializing')
        cens = self.add_cen_eeps(track)

        if cens[0] != 0:
            self.add_quiesscent_he_eep(track, 'YCEN_0.550')
            ihe_beg = track.iptcri[self.ptcri.get_ptcri_name('HE_BEG',
                                                             sandro=False)]

        if ihe_beg == 0 or nsandro_pts <= 10:
            # should now make sure all other eeps are 0.
            [self.add_eep(track, cp, 0, message='no He EEPs')
             for cp in self.ptcri.please_define[5:]]

        self.add_sg_rg_eeps(track)
        self.add_agb_eeps(track)
        self.check_for_monotonic_increase(track)

    def add_ms_beg_eep(self, track, xcen=0.6):
        msg = 'overwrote Sandro for closer match to XCEN=%g' % xcen
        imsbeg = np.argmin(np.abs(xcen - track.data[xcen]))
        if imsbeg > 0:
            self.add_eep(track, 'MS_BEG', imsbeg, message=msg)
        return imsbeg

    def hb_eeps(self, track, diag_plot=True, plot_dir=None):
        '''Call the HB EEP functions.'''
        self.add_hb_beg(track)
        self.add_cen_eeps(track, hb=True)
        self.add_agb_eeps(track, diag_plot=diag_plot, plot_dir=plot_dir)
        return

    def check_pms_beg(self, track):
        '''check age of PMS_BEG'''
        if track.data[age][track.sptcri[0]] <= 0.2:
            self.add_eep(track, 'PMS_BEG',
                         np.nonzero(np.round(track.data[age], 1) > 0.2)[0][0],
                         message='overwritten with age > 0.2')
        return

    def add_tpagb_eeps(self, track, neeps=3):
        '''
        three points for each thermal pulse
        phi_tp = 0.2
        max L
        quessent point (phi_tp max)
        '''
        tp_start, = np.where(track.data['step'] == 1)[0]
        tpage = track.data[age][tp_start:] - track.data[age][tp_start]
        ages = np.linspace(0, tpage[-1], neeps)
        itps = [np.argmin(np.abs(tpage - a)) for a in ages] + tp_start
        self.add_eep(track, 'TPAGB', itps[0], message='TPAGB start')

        for i, itp in enumerate(itps[1:]):
            self.add_eep(track, 'TPAGB{}'.format(i + 1), itp,
                         message='TPAGB age {}'.format(i + 1))
        return

    def add_high_mass_eeps(self, track):
        def add_msbeg(track, start, end):
            # I think Sandro's PMS_END is a little early on the low Z massive
            # tracks...
            if track.Z < 0.004:
                pf_kw = {'get_max': True, 'sandro': True,
                         'more_than_one': 'last',
                         'parametric_interp': False}
                pms_end = self.peak_finder(track, logL, 'PMS_MIN',
                                           'NEAR_ZAM', **pf_kw)
                msg = 'PMS_END fixed by max L between PMS_MIN and MS_BEG'
                self.add_eep(track, 'PMS_END', pms_end, message=msg)

            pf_kw = {'get_max': False, 'sandro': False,
                     'more_than_one': 'min of min'}

            msg = 'Min logL between %s and %s' % (start, end)
            ms_beg = self.peak_finder(track, logL, start, end, **pf_kw)

            if ms_beg == -1:
                msg += ' without parametric'
                pf_kw['parametric_interp'] = False
                ms_beg = self.peak_finder(track, logL, start, end, **pf_kw)

            self.add_eep(track, 'MS_BEG', ms_beg, message=msg)
            return ms_beg

        def add_mstmin(track, start, end, message=None):
            pf_kw = {'get_max': False, 'sandro': False,
                     'more_than_one': 'min of min',
                     'parametric_interp': False}
            ms_tmin = self.peak_finder(track, logT, start, end, **pf_kw)

            self.add_eep(track, 'MS_TMIN', ms_tmin, message=message)
            return ms_tmin

        ms_to = np.nonzero(track.data[xcen] == 0)[0][0]
        self.add_eep(track, 'MS_TO', ms_to, message='XCEN==0')

        if track.Z > 0.01:
            # find tmin before msbeg
            pms_end = track.sptcri[2]
            msg = 'Min logT between %s, %s' % ('PMS_END', 'MS_TO')
            ms_tmin = add_mstmin(track, pms_end, ms_to, message=msg)
            ms_beg = add_msbeg(track, 'PMS_END', 'MS_TMIN')
        else:
            # find msbeg before tmin
            ms_beg = add_msbeg(track, 'PMS_END', 'MS_TO')
            msg = 'Min logT between %s, %s' % ('MS_BEG', 'MS_TO')
            ms_tmin = add_mstmin(track, ms_beg, ms_to, message=msg)

        if ms_tmin ==  -1:
            msg = 'halfway in age between MS_BEG and MS_TO'
            halfway = (track.data[age][ms_to] + track.data[age][ms_beg])/2.
            ms_tmin = np.argmin(np.abs(track.data[age] - halfway))
            self.add_eep(track, 'MS_TMIN', ms_tmin, message=msg)

        fin = len(track.data[logL]) - 1
        cens = self.add_cen_eeps(track, istart=ms_to)
        # in some high mass tracks, YCEN drops very fast so
        # YCEN=0.005's closest match will be at 0.000, in that case
        # cens[-1] will occur at fin even though the track is complete.
        # this is a little reset to push that YCEN=0.000 between
        # YCEN_0.005 and fin
        if track.data[ycen][cens[-2]] == 0.0:
            cens[-1] = (cens[-2] + fin) / 2
            self.add_eep(track, 'YCEN_0.000', cens[-1],
                         message='Reset between YCEN=0.005 and final point')
        heb_beg  = self.add_quiesscent_he_eep(track, cens[0], start=ms_to)
        self.add_eep(track, 'TPAGB', fin, message='Last track value')


        # between ms_to and heb_beg need eeps that are meaningless at high mass:
        _, sg_maxl, rg_minl, rg_bmp1, rg_bmp2, rg_tip, _  = \
            map(int, np.round(np.linspace(ms_to, heb_beg, 7)))
        msg = 'linspace between MS_TO, HE_BEG'
        self.add_eep(track, 'SG_MAXL', sg_maxl, message=msg)
        self.add_eep(track, 'RG_MINL', rg_minl, message=msg)
        self.add_eep(track, 'RG_BMP1', rg_bmp1, message=msg)
        self.add_eep(track, 'RG_BMP2', rg_bmp2, message=msg)
        self.add_eep(track, 'RG_TIP', rg_tip, message=msg)
        self.add_agb_eeps(track)
        # there is a switch for high mass tracks in the add_cen_eeps and
        # add_quiesscent_he_eep functions. If the mass is higher than
        # high_mass the functions use MS_TO as the initial EEP for peak_finder.

        eeps = np.concatenate(([ms_beg, ms_tmin, ms_to, sg_maxl,
                                rg_minl, rg_bmp1, rg_bmp2, rg_tip,
                                heb_beg], cens, [fin]))
        test, = np.nonzero(np.diff(eeps) <= 0)

        if len(test) > 0:
            print('High mass tracks are not monotonically increasing M=%.3f' % track.mass)
            self.check_for_monotonic_increase(track)

        if cens[-1] >= fin:
            track.flag = 'final point on track is cut before final ycen M=%.3f' % track.mass

        return np.concatenate(([ms_beg, ms_tmin, ms_to, heb_beg], cens, [fin]))

    def add_cen_eeps(self, track, hb=False, tol=0.01, istart=None):
        '''
        Add YCEN_%.3f eeps, if YCEN=fraction not found to tol, will add 0 as
        the iptrcri, equivalent to not found.
        '''
        please_define = self.ptcri.please_define
        if hb:
            # HB starts at the beginning
            istart = 0

        if istart is None:
            start = 'RG_TIP'
            pstart = self.ptcri.get_ptcri_name(start, sandro=False)
            istart = track.iptcri[pstart]

        inds = np.arange(istart, len(track.data[ycen]))

        # use defined central values
        # e.g., YCEN_0.500
        cens = [i for i in please_define if i.startswith('YCEN')]
        cens = [float(cen.split('_')[-1]) for cen in cens]
        icens = []
        for cen in cens:
            ind, dif = utils.closest_match(cen, track.data[ycen][inds])
            icen = inds[ind]
            # some tolerance for a good match.
            if dif > tol:
                icen = 0
            self.add_eep(track, 'YCEN_%.3f' % cen, icen, hb=hb,
                         message='YCEN == %.6f' % track.data[ycen][icen])
            # for monotonic increase, even if there is another flare up in
            # He burning, this limits the matching indices to begin at this
            # new eep index.
            inds = np.arange(icen + 1, len(track.data[ycen]))
            icens.append(icen)
        return icens

    def add_hb_beg(self, track):
        '''
        this is just the first line of the track with age > 0.2 yr.
        it could be placed in the load_track method. However, because
        it is not a physically meaningful eep, I'm keeping it here.
        '''
        eep_name = 'HE_BEG'
        hb_beg = track.sptcri[0]
        msg = 'Sandros He1'
        if hb_beg == 0:
            ainds, = np.nonzero(track.data[age] > 0.2)
            hb_beg = ainds[0]
            msg = 'first point with age > 0.2'
        self.add_eep(track, eep_name, hb_beg, hb=True,
                     message=msg)
        return hb_beg

    def add_agb_eeps(self, track, diag_plot=False, plot_dir=None):
        '''
        This is for HB tracks... not sure if it will work for tpagb.

        These EEPS will be when 1) helium (shell) fusion first overpowers
        hydrogen (shell) fusion and 2) when hydrogen wins again (before TPAGB).
        For low-mass HB (<0.485) the hydrogen fusion is VERY low (no atm!),
        and never surpasses helium, this is still a to be done!!
        '''
        def no_agb(track):
            msg = 'no eagb '
            msg1 = msg + 'linspace between YCEN_0.000 and final track point'
            msg2 = msg + 'linspace between YCEN_0.000 and final track point'
            agb_ly1, agb_ly2 = np.round(np.linspace(track.iycen_0000,
                                        track.iptcri[-1], 4))[1:3]
            return agb_ly1, agb_ly2, msg1, msg2

        #if track.mass <= 0.480:
        #    print('HB AGB EEPS might not work for HPHB')

        ly = track.data['LY']
        lx = track.data['LX']

        norm_age = track.data[age]/track.data[age][-1]

        ex_inds, = np.nonzero(track.data[ycen] == 0.00)

        diff_L = np.abs(ly[ex_inds] - lx[ex_inds])
        peak_dict = utils.find_peaks(diff_L)

        # there are probably thermal pulses in the track, taking the first 6
        # mins to try and avoid them. Yeah, I checked by hand, 6 usually works.
        mins = peak_dict['minima_locations'][:6]

        if len(mins) <= 2:
            agb_ly1, agb_ly2, msg1, msg2 = no_agb(track)
        else:
            # the two deepest mins are the ly == lx match
            min_inds = np.asarray(mins)[np.argsort(diff_L[mins])[0:2]]
            (agb_ly1, agb_ly2) = np.sort(ex_inds[min_inds])
            msg1 = 'first deepest min when ly == lx after YCEN_0.000'
            msg2 = 'second deepest mins when ly == lx after YCEN_0.000'
            msg = ''
            # most of the time, the above works, a couple times the points
            # are instead in the thermal pulses.

            # if agb_ly1 is in a thermal pulse (and should be much younger)
            # take away some mins...

            i = 4
            if norm_age[ex_inds[mins[0]]] < 0.89 and norm_age[agb_ly1] > 0.98:
                while norm_age[agb_ly1] > 0.98:
                    mins = mins[:i]
                    min_inds = np.asarray(mins)[np.argsort(diff_L[mins])[0:2]]
                    try:
                        (agb_ly1, agb_ly2) = np.sort(ex_inds[min_inds])
                    except:
                        agb_ly1, agb_ly2, msg1, msg2 = no_agb(track)
                        msg = ''
                        break
                    i -= 1
                msg = ' adjusted to be outside of a TP'

            # if the agb_ly2 is in a thermal pulse take away some mins...
            if norm_age[agb_ly2] > 0.999:
                while norm_age[agb_ly2] > 0.999:
                    mins = mins[:i]
                    min_inds = np.asarray(mins)[np.argsort(diff_L[mins])[0:2]]
                    try:
                        (agb_ly1, agb_ly2) = np.sort(ex_inds[min_inds])
                    except:
                        agb_ly1, agb_ly2, msg1, msg2 = no_agb(track)
                        msg = ''
                        break
                    i -= 1
                msg = ' adjusted to be outside of a TP'
            msg1 += msg
            msg2 += msg

        if agb_ly2 > track.iptcri[-1]:
            _, agb_ly2 = np.round(np.linspace(track.iycen_0000,
                                        track.iptcri[-1], 4))[1:3]
            msg2 += ' was past TPAGB re-adjusted.'
        if agb_ly1 > track.iptcri[-1]:
            agb_ly1, _ = np.round(np.linspace(track.iycen_0000,
                                        track.iptcri[-1], 4))[1:3]
            msg1 += ' was past TPAGB re-adjusted.'

        self.add_eep(track, 'AGB_LY1', agb_ly1, hb=True, message=msg1)
        self.add_eep(track, 'AGB_LY2', agb_ly2, hb=True, message=msg2)

        # HACK UNTIL TPAGB IS FULLY INTEGRATED
        #inds = np.arange(agb_ly2 + 3, track.iptcri[-1], dtype=int)
        #if len(inds) == 0 and track.iptcri[-1] > 0:
        #    if track.iptcri[-1] < agb_ly2:
        #        track.flag = 'TP-AGB is at or before AGB_LY2'
        #        if self.debug:
        #            pdb.set_trace()
        #else:
        #    pd = utils.find_peaks(track.data[logL][inds])
        #    if pd['maxima_number'] >= 1:
        #        #stpagb = second_derivative(track.data[logL][inds], np.log10(track.data['age'][inds]))
        #        pf_kw = {'get_max': True, 'sandro': False, 'more_than_one': 'max of max',
        #                 'parametric_interp': False, 'less_linear_fit': False}
        #        #stpagb = self.peak_finder(track, logL, 'AGB_LY2', 'TPAGB', **pf_kw)
        #        msg = 'Peaks found between AGB_LY2 and TPAGB. Redifining TPAGB'
        #        imax = pd['maxima_locations']
        #        #imin = pd['minima_locations']
        #        tpagb = inds[imax[0]]
                #from padova_tracks.tracks.track_diag import plot_track
                #ax = plot_track(track, 'age', logL)
                #ax.plot(track.data[age][track.iptcri], track.data[logL][track.iptcri], 'o')
                #ax.plot(track.data[age][inds[imin]], track.data[logL][inds[imin]], 'o')
                #ax.plot(track.data[age][stpagb], track.data[logL][stpagb], 's')
                #ax.plot(track.data[age][tpagb], track.data[logL][tpagb], '*')
                #print(track.mass)
                #print(track.Z)
         #       self.add_eep(track, 'TPAGB', tpagb, hb=True, message=msg)

        if diag_plot:
            agb_ly1c = 'red'
            agb_ly2c = 'blue'
            fig, (ax1, ax2) = plt.subplots(ncols=2, figsize=(12, 6))
            ax1.plot(norm_age, ly, label='He', color='purple')
            ax1.plot(norm_age, lx, label='H', color='orange')
            if len(ex_inds) > 0:
                ax1.plot(norm_age[ex_inds], diff_L, label='abs diff', color='black')
                ax1.plot(norm_age[ex_inds[mins]], diff_L[mins], 'o', color='black')
            ax1.plot(norm_age[agb_ly1], lx[agb_ly1], 'o', color=agb_ly1c)
            ax1.plot(norm_age[agb_ly2], ly[agb_ly2], 'o', color=agb_ly2c)

            ax1.set_title(track.mass)
            ax1.legend(loc=0)
            ax1.set_ylim(-0.05, 1.)
            if len(ex_inds) > 0:
                ax1.set_xlim(norm_age[ex_inds[0]], 1)
            ax1.set_ylabel('Luminosity fraction from []')
            ax1.set_xlabel('Age/Total Age')

            ax2.plot(track.data[logT], track.data[logL], color='green')
            inds = track.iptcri[track.iptcri > 0]
            ax2.plot(track.data[logT][inds], track.data[logL][inds], 'o', color='green')
            ax2.plot(track.data[logT][agb_ly1], track.data[logL][agb_ly1],
                     'o', color=agb_ly1c)
            ax2.plot(track.data[logT][agb_ly2], track.data[logL][agb_ly2],
                     'o', color=agb_ly2c)
            ax2.set_xlim(ax2.get_xlim()[::-1])
            ax2.set_xlabel('$\log\ T_{eff}$')
            ax2.set_ylabel('$\log\ L$')

            figname = 'diag_agb_HB_eep_M%s.png' % track.mass
            if plot_dir is not None:
                figname = os.path.join(plot_dir, figname)
            plt.savefig(figname)
            # helpful in ipython:
            #if i == 4:
            #    plt.close()
            plt.close()
            #print('wrote %s' % figname)
        return agb_ly1, agb_ly2

    def add_ms_eeps(self, track):
        '''
        Adds  MS_TMIN and MS_TO.

        MS_TMIN found in this function is either:
        a) np.argmin(logT) between Sandro's MS_BEG and POINT_C
        b) XCEN=0.3 if low mass (low mass value is hard coded and global)
        c) the log te min on the MS found by the second derivative of
            d^2 log_te / d model^2 where model is just the inds between
            MS_BEG and POINT_C (that is, model as in model number from the
            tracks)
        d) zero

        MS_TO is either:
        a) the max log te on the MS found by
           i) by the peak log Te; or
           ii) subtracting off a linear fit in log_te vs model number
            (see c. above)
        b) zero

        if there is an error, either MS_TO or MS_TMIN will -1

        '''

        def delta_te_eeps(track, before, after):
            xdata = track.data[logL]
            return np.abs(np.diff((xdata[before], xdata[after])))
        inds = self.ptcri.inds_between_ptcris(track, 'MS_BEG', 'POINT_C',
                                              sandro=True)

        # transition mass
        if track.mass <= 0.9 and track.mass >= 0.7 and len(inds) == 0:
            ind1 = track.sptcri[self.ptcri.get_ptcri_name('MS_BEG')]
            ind2 = len(track.data[logL]) - 1
            inds = np.arange(ind1, ind2)

        if len(inds) == 0:
            ms_tmin = 0
            msg = 'No points between MS_BEG and POINT_C'
        else:
            xdata = track.data[logT][inds]
            ms_tmin = inds[np.argmin(xdata)]
            delta_te = delta_te_eeps(track, ms_tmin, inds[0])
            msg = 'Min logT'
            if track.mass <= low_mass:
                # BaSTi uses XCEN == 0.3, could put this as a keyword
                xcen = 0.3
                dte = np.abs(track.data[xcen][inds] - xcen)
                ms_tmin = inds[np.argmin(dte)]
                msg = 'XCEN==%.1f' % xcen
            elif delta_te < .1:  # value to use interp instead
                # find the te min by interpolation.
                ms_tmin = second_derivative(xdata, inds)
                msg = 'Min logT by interpolation'

        self.add_eep(track, 'MS_TMIN', ms_tmin, message=msg)

        if ms_tmin == 0:
            ms_to = 0
            msg = 'no MS_TMIN'
        else:
            inds = self.ptcri.inds_between_ptcris(track, 'MS_TMIN', 'RG_BMP1',
                                                  sandro=False)
            eep2 = 'RG_BMP1'
            if len(inds) == 0:
                eep2 = 'final track point'
                inds = np.arange(ms_tmin, len(track.data[logT] - 1))

            ms_to = inds[np.argmax(track.data[logT][inds])]
            msg = 'Max logT between MS_TMIN and either %s' % eep2
            delta_te = delta_te_eeps(track, ms_to, ms_tmin)

            if track.mass <= low_mass or delta_te < 0.01:
                # first try with parametric interpolation
                pf_kw = {'get_max': True, 'sandro': False,
                         'more_than_one': 'max of max',
                         'parametric_interp': False}

                ms_to = self.peak_finder(track, logT, 'MS_TMIN', 'RG_BMP1',
                                         **pf_kw)
                msg = 'Max logT between MS_TMIN and RG_BMP1'
                delta_te = delta_te_eeps(track, ms_to, ms_tmin)
                # if the points are too cluse try with less linear fit
                if ms_to == -1 or delta_te < 0.01:
                    pf_kw['less_linear_fit'] = True
                    ms_to = self.peak_finder(track, logT, 'MS_TMIN',
                                             'RG_BMP1', **pf_kw)
                    msg = 'Max logT between MS_TMIN and RG_BMP1 - linear fit'
                if ms_to == -1 or delta_te < 0.01:
                    pf_kw['less_linear_fit'] = False
                    pf_kw['more_than_one'] = 'last'
                    ms_to = self.peak_finder(track, logT, 'MS_TMIN',
                                             'RG_BMP1', **pf_kw)
                    msg = 'last logT Max between MS_TMIN and RG_BMP1'
            if ms_to == -1:
                # do the same as for tmin... take second deriviative
                xdata = track.data[logL][inds]
                ms_to = second_derivative(xdata, inds)
                msg = 'Min logL between MS_TMIN and RG_BMP1 by interpolation'
                if ms_to == -1:
                    ms_to = inds[np.nonzero(track.data[xcen][inds] == 0)[0][0]]
                    msg = 'XCEN==0 as last resort'
            if ms_to == -1:
                # tried four ways!?!!
                msg = 'No MS_TO found after four methods'
                ms_to = 0
        self.add_eep(track, 'MS_TO', ms_to, message=msg)

        if ms_to == 0:
            if track.mass > low_mass:
                print('MS_TO and MS_TMIN found by age limits %.4f' % track.mass)
            ms_beg = track.iptcri[self.ptcri.get_ptcri_name('MS_BEG',
                                                            sandro=False)]
            fin = len(track.data)
            half_way = ms_beg + (fin - ms_beg) / 2
            self.add_eep(track, 'MS_TMIN', half_way,
                         message='Half way from MS_BEG to Fin')
            #self.add_eep_with_age(track, 'MS_TMIN', (13.7e9/2.))
            self.add_eep_with_age(track, 'MS_TO', max_age)
        return ms_tmin, ms_to

    def add_sg_rg_eeps(self, track):
        '''
        Add SG_MAXL and RG_MINL eeps.

        SG_MAXL and RG_MINL are based on the morphology on the HRD.
        The morphology of the HRD in this region changes drastically across
        the mass and metallicity parameter space.

        This function calls add_sg_maxl_eep and add_rg_minl_eep in different
        ways to pull out the correct values of each.
        '''
        def check_minl(imin_l, msto, track):
            return [imin_l - msto < 50,
                    imin_l == -1,
                    (np.abs(imin_l - track.sptcri[7]) > 100),
                    np.round(track.data[xcen][imin_l], 4) > 0]

        eep2 = 'RG_BMP1'
        msto = track.iptcri[self.ptcri.get_ptcri_name('MS_TO', sandro=False)]

        more_than_one = 'last'

        # first shot, uses the last logL min after the MS_TO before RG_BMP1
        imin_l = self.add_rg_minl_eep(track, eep2=eep2,
                                      more_than_one=more_than_one)

        more_than_ones = ['last', 'first', 'min of min']
        i = 0
        while True in check_minl(imin_l, msto, track):
            # try using the min of the logL mins between MS_TO and RG_BMP1
            if i == 3:
                break
            imin_l = self.add_rg_minl_eep(track, more_than_one=more_than_ones[i])
            i += 1

        i == 0
        while True in check_minl(imin_l, msto, track):
            # ok, try to do SG_MAXL first, though typically the issues
            # in RG_MAXL are on the RG_BMP1 side ...
            # print('failed to find RG_MINL before SG_MAXL')
            if i == 3:
                break
            imax_l = self.add_sg_maxl_eep(track, eep2=eep2)
            imin_l = self.add_rg_minl_eep(track, eep1='SG_MAXL', eep2=eep2,
                                          more_than_one=more_than_ones[i])
            i += 1

        if True in check_minl(imin_l, msto, track):
            imin_l = track.sptcri[7]
            msg = 'Set RG_MINL to Sandro\'s RG_BASE'
            self.add_eep(track, 'RG_MINL', imin_l, message=msg)

        if not True in check_minl(imin_l, msto, track):
            imin_l = track.sptcri[7]
            msg = 'Set RG_MINL to Sandro\'s RG_BASE'
            self.add_eep(track, 'RG_MINL', imin_l, message=msg)
            # find the SG_MAXL between MS_TO and RG_MINL

        imax_l = self.add_sg_maxl_eep(track)
        # high mass, low z, have hard to find base of rg, but easier to find
        # sg_maxl. This flips the order of finding. Also an issue is if
        # the L min after the MS_TO is much easier to find than the RG Base.
        if imax_l <= 0:
            imax_l = self.add_sg_maxl_eep(track, eep2=eep2)
            #imin_l = self.add_rg_minl_eep(track, eep1='SG_MAXL', eep2=eep2)

        if imax_l == -1:
            self.check_for_monotonic_increase(track)

        #if np.round(track.data[xcen][imin_l], 4) > 0 or imin_l < 0:


        return

    def add_rg_minl_eep(self, track, eep1='MS_TO', eep2='RG_BMP1',
                        more_than_one='last'):
        '''
        Add RG_MINL eep.

        The MIN L before the RGB for high mass or the base of the
        RGB for low mass.

        Parameters
        ----------
        track : object
            track object
        eep1 : string ['MS_TO']
            earlier EEP sent to self.peak_finder
        eep2 : string ['RG_BMP1']
            later EEP sent to self.peak_finder
        more_than_one : string
            extrema value sent to self.peak_finder

        Returns
        -------
        min_l : int
            track.data index of RG_MINL eep
        '''
        # find min_l with parametric interp and using the more_than_one min.
        pf_kw = {'sandro': False, 'more_than_one': more_than_one}
        min_l = self.peak_finder(track, logL, eep1, eep2, **pf_kw)
        msg = '%s Min logL between %s and %s' % (more_than_one, eep1, eep2)
        msg += ' with parametric interp'
        if min_l == -1 or track.mass < low_mass:
            # try without parametric interp and with less linear fit
            pf_kw.update({'parametric_interp': False, 'less_linear_fit': True})
            msg = msg.replace('parametric interp', 'less linear fit')
            min_l = self.peak_finder(track, logL, eep1, eep2, **pf_kw)

        if min_l == -1:
            # try without parametric interp and without less linear fit
            pf_kw.update({'less_linear_fit': False})
            msg = msg.replace('less linear fit', '')
            min_l = self.peak_finder(track, logL, eep1, eep2, **pf_kw)

        self.add_eep(track, 'RG_MINL', min_l, message=msg)
        return min_l

    def add_sg_maxl_eep(self, track, eep2='RG_MINL'):
        '''
        Add SG_MAXL eep between MS_TO and eep2

        If mass > inte_mass will take SG_MAXL to be the mean age
        between MSTO and RG_MINL

        Will first try peak finder between MS_TO and eep2 and take the
        max of max (if eep2 is RG_MINL) or last max.

        If SG_MAXL is within 10 inds of RG_MINL, will try peak finder
        with less linear fit, and if that's still a problem, will hack
        a simpler less linear fit.

        Parameters
        ----------
        track : object
            track object
        eep2 : string ['RG_MINL']
            later EEP sent to self.peak_finder

        Returns
        -------
        max_l : int
            track.data index of SG_MAXL eep
        '''
        if track.mass > inte_mass:
            irg_minl = self.ptcri.get_ptcri_name('RG_MINL', sandro=False)
            imsto = self.ptcri.get_ptcri_name('MS_TO', sandro=False)
            rg_minl = track.iptcri[irg_minl]
            msto = track.iptcri[imsto]
            mean_age = np.mean([track.data[age][msto], track.data[age][rg_minl]])
            max_l = np.argmin(np.abs(track.data[age] - mean_age))
            msg = 'Set SG_MAXL to be mean age between MS_TO and RG_MINL'
            self.add_eep(track, 'SG_MAXL', max_l, message=msg)
            #self.check_for_monotonic_increase(track)
            return max_l

        extreme = 'max of max'
        if eep2 != 'RG_MINL':
            extreme = 'last'

        pf_kw = {'get_max': True, 'sandro': False, 'more_than_one': extreme,
                 'parametric_interp': False, 'less_linear_fit': False}


        max_l = self.peak_finder(track, logL, 'MS_TO', eep2, **pf_kw)
        msg = '%s logL between MS_TO and %s' % (extreme, eep2)

        rg_minl = track.iptcri[self.ptcri.get_ptcri_name('RG_MINL',
                                                         sandro=False)]

        if max_l == -1 or np.abs(rg_minl - max_l) < 10:
            pf_kw['less_linear_fit'] = bool(np.abs(pf_kw['less_linear_fit']-1))
            msg = '%s logL MS_TO to %s less_linear_fit' % (extreme, eep2)
            max_l = self.peak_finder(track, logL, 'MS_TO', eep2, **pf_kw)

        if np.abs(rg_minl - max_l) < 10:
            inds = self.ptcri.inds_between_ptcris(track, 'MS_TO', eep2,
                                                  sandro=False)
            non_dupes = self.remove_dupes(track.data[logT][inds],
                                          track.data[logL][inds], '',
                                          just_two=True)

            xdata = track.data[logT][inds][non_dupes]
            ydata = track.data[logL][inds][non_dupes]
            # calculate slope using polyfit
            m, bb = np.polyfit(xdata, ydata, 1)
            peak_dict = utils.find_peaks(ydata - (m * xdata + bb))
            maxs = peak_dict['maxima_locations']
            max_l = inds[non_dupes[maxs[np.argmax(xdata[maxs])]]]
            msg = 'Hacked SG_MAXL because it was too close to RG_MINL'

        msto = track.iptcri[self.ptcri.get_ptcri_name('MS_TO', sandro=False)]
        if max_l == msto:
            print('SG_MAXL is at MS_TO!')
            print('XCEN at MS_TO (%i): %.3f' % (msto, track.data[xcen][msto]))
            max_l = -1
            msg = 'SG_MAXL is at MS_TO'
        self.add_eep(track, 'SG_MAXL', max_l, message=msg)
        return max_l

    def add_eep_with_age(self, track, eep_name, age, tol=0.1):
        iage = np.argmin(np.abs(track.data[age] - age))
        age_diff = np.min(np.abs(track.data[age] - age))
        msg = 'By age = %g and is %g' % (age, track.data[age][iage])
        #if (age_diff / age) > tol:
        #    print('possible bad age match for eep.')
        #    print('frac diff mass eep_name age_attempted age_set')
        #    print('%g' % (age_diff/age), track.mass, eep_name,
        #          '%g' % age, '%g' % track.data[age][iage])
        self.add_eep(track, eep_name, iage, message=msg)
        return iage, track.data[age][iage]

    def add_eep(self, track, eep_name, ind, hb=False, message='no info',
                loud=False):
        '''
        Will add or replace the index of Track.data to track.iptcri
        '''
        track.iptcri[self.ptcri.key_dict[eep_name]] = ind
        track.__setattr__('i{:s}'.format(eep_name.lower().replace('.','')), ind)
        track.info['%s' %  eep_name] = message
        if loud:
            print(track.mass, eep_name, ind, message)

    def load_critical_points(self, track, ptcri, hb=False, plot_dir=None,
                             diag_plot=True, debug=False):
        '''
        Load all EEPs. First the ones defined by Sandro, then call
        define_eep_stages

        Parameters
        ----------
        track : object
            rsp.padova_tracks.Track object

        ptcri : flexible
            rsp.padova_tracks.critical_point object or filename of ptcri
            file

        hb : bool [False]
            is this an HB track

        plot_dir : str
            path to diagnostic plot directory

        diag_plot : bool [True]
            make diagnostic plots

        debug : bool [False]
            debug errors with pbd

        Returns
        -------
        Adds the following attributes:
        ptcri : the critical_point object
        track.iptcri : the critical point index rel to track.data
        track.mptcri : the model number of the critical point
        '''
        if track.flag is not None:
            return track

        self.debug = debug
        #assert ptcri is not None, \
        #    'Must supply either a ptcri file or object'

        if type(ptcri) is str:
            ptcri = critical_point(ptcri, hb=hb)
        self.ptcri = ptcri
        eep_obj = self.ptcri.eep
        please_define = self.ptcri.please_define
        eep_list = self.ptcri.eep_list

        if hasattr(ptcri, 'Z'):
            assert ptcri.Z == track.Z, \
                'Zs do not match between track and ptcri file %f != %f' % (ptcri.Z,
                                                                           track.Z)
        if hasattr(ptcri, 'Y'):
            assert np.round(ptcri.Y, 2) == np.round(track.Y, 2),  \
                'Ys do not match between track and ptcri file %f != %f' % (ptcri.Y,
                                                                       track.Y)

        #if hb and len(ptcri.please_define_hb) > 0:
        #    # Initialize iptcri for HB
        #    track.iptcri = np.zeros(len(eep_obj.eep_list_hb), dtype=int)
        #    self.define_eep_stages(track, hb=hb, plot_dir=plot_dir,
        #                           diag_plot=diag_plot, debug=debug)
        #else:
            # Sandro's definitions. (I don't use his HB EEPs)

        try:
            mptcri = ptcri.data_dict['M%.3f' % track.mass]
        except KeyError:
            print('M=%.4f not found in %s' % \
                  (track.mass, os.path.join(self.ptcri.base,
                                            self.ptcri.name)))
            track.flag = 'no ptcri mass'
            return track
        track.sptcri = \
            np.concatenate([np.nonzero(track.data[MODE] == m)[0]
                            for m in mptcri])
        if len(track.sptcri) != len(np.nonzero(mptcri)[0]):
            if len(np.nonzero(mptcri)[0]) - len(track.sptcri) == 1:
                # Sandro truncated the track after making the ptcri file
                track.sptcri = np.append(track.sptcri, len(track.data[logL]) - 1)
                mptcri[-1] = len(track.data[logL]) + 1
            else:
                track.flag = 'ptcri file does not match track, not enough MODEs'
                ind, = np.nonzero(self.ptcri.masses == track.mass)
                self.ptcri.fix_ptcri(self.ptcri.fnames[ind])

        if len(please_define) > 0:

            # Initialize iptcri
            track.iptcri = np.zeros(len(eep_list), dtype=int)

            # Get the values that we won't be replacing.
            pinds = np.array([i for i, a in enumerate(eep_list)
                              if a in self.ptcri.sandro_eeps])

            sinds = \
                np.array([i for i, a in enumerate(self.ptcri.sandro_eeps)
                          if a in eep_list])

            # they may all be replaced!
            if len(pinds) > 0 and len(sinds) > 0:
                track.iptcri[pinds] = mptcri[sinds] - 2

            # but if the track did not actually make it to that EEP, no -2!
            track.iptcri[track.iptcri < 0] = 0

            # and if sandro cut the track before it reached this point,
            # no index error!
            track.iptcri[track.iptcri > len(track.data[MODE])] = 0

            # define the eeps
            self.define_eep_stages(track, hb=hb, plot_dir=plot_dir,
                                   diag_plot=diag_plot, debug=debug)
        else:
            # copy sandros dict.
            track.iptcri = ptcri.data_dict['M%.3f' % track.mass]
        return track

    def add_quiesscent_he_eep(self, track, ycen1, start='RG_TIP'):
        """
        Add HEB_BEG eep.

        He fusion starts after the RGB, but where? It was tempting to simply
        choose the min L on the HeB, but that could come after 1/2 the YCEN
        was burned for massive stars. I decided to find a place after the RGB
        where there was a bump in YCEN, a little spurt before it started
        burning He at a more consistent rate.

        The above method was not stable for all Z. I've instead moved to
        where there is a min after the TRGB in LY, that is it dips as the
        star contracts, and then ramps up.

        Parameters
        ----------
        track : object
            rsp.padova_tracks.Track object

        ycen1 : str
            end EEP to look for beginning of He burning

        start : str ['RG_TIP']
            start EEP to look for beginning of He burning

        Returns
        -------
        he_beg : int
            track.data index of HE_BEG
        """
        if type(ycen1) != str:
            inds = np.arange(start, ycen1)
        else:
            inds = self.ptcri.inds_between_ptcris(track, start, ycen1,
                                                  sandro=False)
        eep_name = 'HE_BEG'

        if len(inds) == 0:
            self.add_eep(track, eep_name, 0,
                         message='No HE_BEG M=%.4f Z=%.4f' % (track.mass,
                                                              track.Z))
            return 0

        he_min = np.argmin(track.data['LY'][inds])

        # Sometimes there is a huge peak in LY before the min, find it...
        npts = inds[-1] - inds[0] + 1
        subset = npts / 3
        he_max = np.argmax(track.data['LY'][inds[:subset]])

        # Peak isn't as important as the ratio between the start and end
        rat = track.data['LY'][inds[he_max]] / track.data['LY'][inds[0]]

        # If the min is at the point next to the RG_TIP, or the ratio is huge,
        # get the min after the peak.
        if he_min == 0 or rat > 10:
            amin = np.argmin(track.data['LY'][inds[he_max + 1:]])
            he_min = he_max + 1 + amin

        he_beg = inds[he_min]
        self.add_eep(track, eep_name, he_beg, message='Min LY after RG_TIP')
        return he_beg

class InDevelopment(object):
    """
    half baked or unfinished
    """
    def first_check():
        ''' wip: toward eleminating the use of Sandro's eeps '''
        for i in range(70):
            ind = [ farther(inds1, i, 5)]

    def farther(arr, ind, dist):
        ''' wip: toward eleminating the use of Sandro's eeps '''
        return arr[np.nonzero(np.abs(arr - arr[ind]) > dist)[0]]

    def recursive_farther(arr, dist, n):
        ''' wip: toward eleminating the use of Sandro's eeps '''
        saved = [arr[0]]
        for i in range(n):
            if i == 0:
                narr = farther(arr, 0, dist)
                print(i, narr)
            else:
                narr = farther(narr, 0, dist)
                print(i, narr)
            saved.append(narr[0])
            #if saved[i] == saved[i-1]:
            #    break
        return saved

    def convective_core_test(self, track):
        '''
        only uses sandro's defs, so doesn't need load_critical_points
        initialized.
        '''
        ycols = ['QSCHW', 'QH1', 'QH2']
        age = track.data[age]
        lage = np.log10(age)

        morigs = [t for t in self.ptcri.data_dict['M%.3f' % self.mass]
                  if t > 0 and t < len(track.data[logL])]
        iorigs = [np.nonzero(track.data[MODE] == m)[0][0] for m in morigs]
        try:
            inds = self.ptcri.inds_between_ptcris(track, 'MS_BEG', 'POINT_B',
                                                  sandro=True)
        except IndexError:
            inds, = np.nonzero(age > 0.2)

        try:
            lage[inds]
        except IndexError:
            inds = np.arange(len(lage))
        plt.figure()
        ax = plt.axes()
        for ycol in ycols:
            ax.plot(lage[inds], track.data[ycol][inds], lw=2, label=ycol)
            ax.scatter(lage[iorigs[4]], track.data[ycol][iorigs[4]], s=100,
                       marker='o', color='red')
            if len(iorigs) >= 7:
                ax.scatter(lage[iorigs[7]], track.data[ycol][iorigs[7]], s=100,
                           marker='o', color='blue')
                xmax = lage[iorigs[7]] + .4
            else:
                xmax = ax.get_xlim()[1]

        xmin = lage[iorigs[4]] - .4
        ax.set_xlim(xmin, xmax)
        ax.set_title(self.mass)
        ax.legend(loc=0)


    def strip_instablities(self, track, inds):
        return track
        peak_dict = utils.find_peaks(track.data[logL][inds])
        extrema = np.sort(np.concatenate([peak_dict['maxima_locations'],
                                          peak_dict['minima_locations']]))
        # divide into jumps that are at least 50 models apart
        jumps, = np.nonzero(np.diff(extrema) > 50)
        if len(jumps) == 0:
            print('no istabilities found')
            return track
        if not hasattr(track, 'data_orig'):
            track.data_orig = copy.copy(track.data)
        # add the final point
        jumps = np.append(jumps, len(extrema) - 1)
        # instability is defined by having more than 20 extrema
        jumps = jumps[np.diff(np.append(jumps, extrema[-1])) > 20]
        # np.diff is off by one in the way I am about to use it
        # burn back some model points to blend better with the old curve...
        starts = jumps[:-1] + 1
        ends = jumps[1:]
        # the inds to smooth.
        for i in range(len(jumps)-1):
            moffset = (inds[extrema[ends[i]]] - inds[extrema[starts[i]]]) / 10
            poffset = moffset
            if i == len(jumps)-2:
                poffset = 0
            finds = np.arange(inds[extrema[starts[i]]] - moffset,
                              inds[extrema[ends[i]]] + poffset)
            tckp, step_size, non_dupes = self._interpolate(track, finds, s=0.2,
                                                                   linear=True)
            arb_arr = np.arange(0, 1, step_size)
            if len(arb_arr) > len(finds):
                arb_arr = np.linspace(0, 1, len(finds))
            else:
                print(len(finds), len(xnew))
            agenew, xnew, ynew = splev(arb_arr, tckp)
            #ax.plot(xnew, ynew)
            track.data[logL][finds] = ynew
            track.data[logT][finds] = xnew
            track.data[age][finds] = agenew
            print('logL, logT, age interpolated from inds %i:%i' %
                  (finds[0], finds[-1]))
            track.header.append('logL, logT, age interpolated from MODE %i:%i \n' % (track.data[MODE][finds][0], track.data[MODE][finds][-1]))

            self.check_strip_instablities(track)
        return track

    def check_strip_instablities(self, track):
        fig, (axs) = plt.subplots(ncols=2, figsize=(16, 10))
        for ax, xcol in zip(axs, [age, logT]):
            for data, alpha in zip([track.data_orig, track.data], [0.3, 1]):
                ax.plot(data[xcol], data[logL], color='k', alpha=alpha)
                ax.plot(data[xcol], data[logL], ',', color='k')

            ax.set_xlabel('$%s$' % xcol.replace('_', r'\! '), fontsize=20)
            ax.set_ylabel('$LOG\! L$', fontsize=20)
        plt.show()
        '''
        I'm currently not doing shit with this... it's such a fast track it
        wont make a big difference in MATCH.
        In any case, hopefully MATCH treats these reasons as blurs on a cmd
        as they should probably be treated...

        # there are instabilities in massive tracks that are on the verge or
        # returning to the hot side (Teff>10,000) of the HRD before TPAGB.
        # The following is designed to cut the tracks before the instability.
        # If the star is M>55. and the last model doesn't reach Teff = 10**4,
        # The track is cut at the max logL after the MS_TO, otherwise, that
        # value is the TPAGB (not actually TP-AGB, but end of the track).
        fin = len(track.data[logL]) - 1
        inds = np.arange(ms_to, fin)
        peak_dict = utils.find_peaks(track.data[logL][inds])
        max_frac = peak_dict['maxima_number'] / float(len(inds))
        min_frac = peak_dict['minima_number'] / float(len(inds))
        if min_frac > 0.15 or max_frac > 0.15:
            print('M=%.3f' % track.mass)
            print('MS_TO+ %i inds. Fracs: max %.2f, min %.2f' %
                  (len(inds), max_frac, min_frac))
            print('MS_TO+ minima_number', peak_dict['minima_number'])
            print('MS_TO+ maxima_number', peak_dict['maxima_number'])
            track = self.strip_instablities(track, inds)
        '''

    def check_sandros_eeps(self, track):
        '''
        Sometimes Sandro's points are wrong or poorly placed. This is a
        hack until I completely remove dependance on his eeps
        The reason the hack can work is because these eeps have no physical
        meaning, so adjusting them one or two points adjacent on the track
        should be fine.
        '''
        loud = True
        errmsg = 'Track is unworkable. Check Sandro\'s eeps'
        msg = '%s too close, moved this one away'
        eep = Eep()
        inds, = np.nonzero(track.iptcri > 0)
        idefined = np.array(track.iptcri)[inds]
        defined = np.array(eep.eep_list)[inds]

        if np.min(np.diff(idefined)) <= 1:
            same = np.argmin(np.diff(idefined))
            isame = idefined[same]

            after = same + 1
            iafter = idefined[after]

            before = same - 1
            ibefore = idefined[before]
            if iafter - ibefore < 5:
                # can't space them with one ind in between!
                # must move the before or after eep.
                earlier = eep.eep_list[eep.eep_list.index(defined[before]) - 1]
                later = eep.eep_list[eep.eep_list.index(defined[after]) + 1]
                iearlier = track.iptcri[self.ptcri.get_ptcri_name(earlier,
                                                                  sandro=False)]
                ilater = track.iptcri[self.ptcri.get_ptcri_name(later,
                                                                sandro=False)]
                # is there space to adjust now?
                if ilater - iearlier < 9:
                    track.flag = errmsg
                    return

                # move the point toward where there is more room
                if iafter - isame < isame - ibefore:
                    inew = iafter + 1
                    inew_name = defined[after]
                else:
                    inew = ibefore - 1
                    inew_name = defined[before]
            else:
                # can shift the offender!
                if iafter - isame < isame - ibefore:
                    inew = isame - 1
                else:
                    inew = isame + 1
                inew_name = defined[same]

            self.add_eep(track, inew_name, inew, loud=loud,
                         message=msg % defined[same])

            if np.min(np.diff(track.iptcri)) <= 1:
                self.check_sandros_eeps(track)
