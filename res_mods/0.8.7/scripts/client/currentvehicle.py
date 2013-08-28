# Embedded file name: scripts/client/CurrentVehicle.py
import BigWorld
from items import vehicles
from AccountCommands import LOCK_REASON
from account_helpers.AccountSettings import AccountSettings
from account_helpers.AccountPrebattle import AccountPrebattle
from adisp import process, async
from Event import Event, EventManager
from gui.Scaleform.Waiting import Waiting
from gui.Scaleform.gui_items import FittingItem
from debug_utils import *
import io, os, json, codecs, math
from items import tankmen
import thread

class _CurrentVehicle(object):

	def __init__(self):
		self.firstTimeInitialized = False
		self.__eventManager = EventManager()
		self.onChanged = Event(self.__eventManager)
		self.onChanging = Event(self.__eventManager)
		self.__vehicle = None
		self.__crew = {}
		self.__changeCallbackID = None
		self.__clanLock = None
		return

	def __reset(self):
		self.firstTimeInitialized = False
		self.__vehicle = None
		return

	def isVehicleTypeLocked(self):
		return self.__clanLock is not None

	def cleanup(self):
		self.reset(True)
		self.__eventManager.clear()

	def __setVehicleToServer(self, id):
		AccountSettings.setFavorites('current', id)

	def __repr__(self):
		return 'CurrentVehicle(%s)' % str(self.__vehicle)

	def __getVehicle(self):
		return self.__vehicle

	def __setVehicle(self, newVehicle):
		self.__request(newVehicle.inventoryId)
		g_currentVehicle.onChanging()

	def setVehicleById(self, id):
		self.__request(id)

	vehicle = property(__getVehicle, __setVehicle)

	def __getRepairCost(self):
		return self.__vehicle.repairCost

	def __setRepairCost(self, newValue):
		if self.__vehicle.repairCost != newValue:
			self.__vehicle.repairCost = newValue
			self.onChanged()

	repairCost = property(__getRepairCost, __setRepairCost)

	def isBroken(self):
		return self.__vehicle.repairCost > 0

	def setLocked(self, newValue):
		if self.__vehicle.lock != newValue:
			self.__vehicle.lock = newValue
			self.onChanged()

	def isCrewFull(self):
		return self.isPresent() and None not in self.__vehicle.crew and self.__vehicle.crew != []

	def isInBattle(self):
		return self.__vehicle.lock == LOCK_REASON.ON_ARENA

	def isInHangar(self):
		return self.isPresent() and not self.isInBattle()

	def isAwaitingBattle(self):
		return self.__vehicle.lock == LOCK_REASON.IN_QUEUE

	def isLocked(self):
		return self.__vehicle.lock != LOCK_REASON.NONE

	def isAlive(self):
		return self.isPresent() and not self.isBroken() and not self.isLocked()

	def isReadyToFight(self):
		isBS = AccountPrebattle.isBattleSession()
		if isBS:
			isBSVehicleLockMode = bool(AccountPrebattle.getSettings()['vehicleLockMode'])
			isCurrentVehicleTypeLocked = self.isVehicleTypeLocked()
			if isBSVehicleLockMode and isCurrentVehicleTypeLocked:
				return False
		return self.isAlive() and self.isCrewFull()

	def isPresent(self):
		return self.__vehicle is not None

	def getState(self):
		if not self.isInHangar():
			return None
		else:
			return self.vehicle.getState()

	def getHangarMessage(self):
		from gui.Scaleform.utils.gui_items import InventoryVehicle
		if self.vehicle is None:
			return ('#menu:currentVehicleStatus/notpresent', InventoryVehicle.STATE_LEVEL.CRITICAL)
		else:
			return ('#menu:currentVehicleStatus/' + self.__vehicle.getState(), self.__vehicle.getStateLevel())

	def getReadyMessage(self):
		return self.getHangarMessage()

	def reset(self, silent = False):
		self.__reset()
		if not silent:
			self.onChanged()

	@process
	def __request(self, inventoryId):
		Waiting.show('updateCurrentVehicle', True)
		from gui.Scaleform.utils.requesters import Requester, StatsRequester, VehicleItemsRequester, InventoryRequester
		vehicles = yield Requester('vehicle').getFromInventory()
		vehicleTypeLocks = yield StatsRequester().getVehicleTypeLocks()
		globalVehicleLocks = yield StatsRequester().getGlobalVehicleLocks()
		old = self.__vehicle
		self.__vehicle = self.__findCurrent(inventoryId, vehicles)
		self.item = yield self.__requestVehicleItem(inventoryId)
		if self.__vehicle and self.__vehicle != old:
			self.__setVehicleToServer(self.__vehicle.inventoryId)
		self.__clanLock = None
		if g_currentVehicle.isPresent():
			clanDamageLock = vehicleTypeLocks.get(self.__vehicle.descriptor.type.compactDescr, {}).get(1, None)
			clanNewbeLock = globalVehicleLocks.get(1, None)
			if not clanDamageLock:
				self.__clanLock = clanNewbeLock
			self.__changeCallbackID = self.__changeCallbackID or BigWorld.callback(0.1, self.__changeDone)

		# Set Defaults
		xvm_conf = []

		# Load configuration
		xvm_configuration_file = os.getcwd() + os.sep + 'res_mods' + os.sep + 'xvm' + os.sep + 'tankrange.xc'
		if not os.path.exists(xvm_configuration_file):
			LOG_NOTE("Configuration file missing (" + xvm_configuration_file + "). Creating.")
		else:
			data = ""
			blockComment = False

			f = codecs.open(xvm_configuration_file, 'r', '"utf-8-sig"')
			for line in f.read().split('\n'):
				line = line.strip()
				if line != "":
					# Start of block comment
					comment = line.find("/*")
					if comment != -1 and comment == 0:
						blockComment = True
						continue

					# End of block comment
					comment = line.find("*/")
					if comment != -1:
						blockComment = False
						continue

					# Block Comment
					if blockComment == True:
						continue

					# Start of line comment
					comment = line.find("//")
					if comment != -1 and comment == 0:
						continue

					# Remove end of line comments
					position = 0
					for i in range(0,line.count("//")):
						comment = line.find("//", position+2)
						if comment != -1:
							colon = line.find(":")

							startSpeach = line.find("\"", colon+1)
							if startSpeach > comment:
								line = line[:comment].strip()

							endSpeach = line.find("\"", startSpeach+1)
							if comment > endSpeach:
								line = line[:comment].strip()

						position += comment

					if line != "":
						data += line + '\n'
			f.close()

			xvm_conf = json.loads(data)

		# Make sure we have the correct defaults
		if not "tankrange" in xvm_conf:
			xvm_conf["tankrange"] = {}

		if not "logging" in xvm_conf["tankrange"]:
			xvm_conf["tankrange"]["logging"] = True

		if not "view_circle" in xvm_conf["tankrange"]:
			xvm_conf["tankrange"]["view_circle"] =  {
				"enabled": True,
				"color": "0xFFFFFF",
				"alpha": 50,
				"thickness": 0.5
			}

		if not "binocular_circle" in xvm_conf["tankrange"]:
			xvm_conf["tankrange"]["binocular_circle"] =  {
				"enabled": True,
				"color": "0xFFFFFF",
				"alpha": 50,
				"thickness": 0.5
			}

		if not "artillery" in xvm_conf["tankrange"]:
			xvm_conf["tankrange"]["artillery"] =  {
				"ignore": False,
				"circle": {
					"enabled": True,
					"color": "0xFF0000",
					"alpha": 50,
					"thickness": 0.5
				}
			}


		# Setup Circles Dictionary
		if not "circles" in xvm_conf:
			xvm_conf["circles"] = { "enabled": True }

		if not "major" in xvm_conf["circles"]:
			xvm_conf["circles"]["major"] = [
				{ "enabled": False, "distance": 445, "thickness": 0.75, "alpha": 45, "color": "0xFFCC66" },
				{ "enabled": False, "distance": 50, "thickness": 1.00, "alpha": 100, "color": "0xFFFFFF" }
			]

		if not "special" in xvm_conf["circles"]:
			xvm_conf["circles"]["special"] = {}

		# Setup Circle's References
		xvm_conf["circle_view"] = { "enabled": True, "color": xvm_conf["tankrange"]["view_circle"]["color"], "alpha": xvm_conf["tankrange"]["view_circle"]["alpha"], "thickness": xvm_conf["tankrange"]["view_circle"]["thickness"]}
		xvm_conf["circle_binocular"] = { "enabled": True, "color": xvm_conf["tankrange"]["binocular_circle"]["color"], "alpha": xvm_conf["tankrange"]["binocular_circle"]["alpha"], "thickness": xvm_conf["tankrange"]["binocular_circle"]["thickness"]}
		xvm_conf["circle_artillery"] = { "enabled": True, "color": xvm_conf["tankrange"]["artillery"]["circle"]["color"], "alpha": xvm_conf["tankrange"]["artillery"]["circle"]["alpha"], "thickness": xvm_conf["tankrange"]["artillery"]["circle"]["thickness"]}

		# Get name
		tank_name = self.__vehicle.descriptor.type.name.split(":")[1].lower().replace("-","_")
		if xvm_conf["tankrange"]["logging"]:
			LOG_NOTE("Tank Name: ", tank_name)

		# Remove current circles
		remaining = []
		for tank_data in xvm_conf["circles"]["special"]:
			if tank_data.keys()[0] != tank_name:
				remaining.append(tank_data)
		xvm_conf["circles"]["special"] = remaining

		# Get type
		if xvm_conf["tankrange"]["artillery"]["ignore"] and "SPG" in self.__vehicle.descriptor.type.tags:
			f = codecs.open(xvm_configuration_file, 'w', '"utf-8-sig"')
			f.write(unicode(json.dumps(xvm_conf, ensure_ascii=False, indent=2)))
			f.close()

			if xvm_conf["tankrange"]["logging"]:
				LOG_NOTE("Ignoring " + vehicle_type + " tank.")
			return

		# Get view distance
		view_distance = self.__vehicle.descriptor.turret["circularVisionRadius"]
		if xvm_conf["tankrange"]["logging"]:
			LOG_NOTE("Base View Range: ", view_distance)

		# Check for Ventilation
		ventilation = self.__isOptionalEquipped("improvedVentilation")
		if xvm_conf["tankrange"]["logging"] and ventilation:
			LOG_NOTE("Ventilation Found")

		# Check for Consumable
		consumable = self.__isConsumableEquipped("ration")
		if xvm_conf["tankrange"]["logging"] and consumable:
			LOG_NOTE("Premium Consumable Found")

		# Update crew
		self.__updateCrew()

		# Check for Brothers In Arms
		brothers_in_arms = True
		for name, data in self.__crew.iteritems():
			if "brotherhood" not in data["skill"]:
				brothers_in_arms = False

		if xvm_conf["tankrange"]["logging"] and brothers_in_arms:
			LOG_NOTE("BIA Found")

		# Calculate commander bonus
		commander_skill = 0
		if "commander" in self.__crew:
			commander_skill = self.__crew["commander"]["level"]

			if brothers_in_arms == True:
				commander_skill += 5
			if ventilation == True:
				commander_skill += 5
			if consumable == True:
				commander_skill += 10

			if xvm_conf["tankrange"]["logging"]:
				LOG_NOTE("Commander Skill: ", commander_skill)

		# Calculate other bonuses
		other_bonus = 1.0
		for name, data in self.__crew.iteritems():
			# Calculate recon skills
			if "commander_eagleEye" in data["skill"]:
				other_bonus *= 1.0 + ( 0.0002 * data["skill"]["commander_eagleEye"] )

				if xvm_conf["tankrange"]["logging"]:
					LOG_NOTE("Recon Bonus: ", 1.0 + ( 0.0002 * data["skill"]["commander_eagleEye"] ))

			# Calculate Situational Awareness Skill
			if "radioman_finder" in data["skill"]:
				other_bonus *= 1.0 + ( 0.0002 * data["skill"]["radioman_finder"] )

				if xvm_conf["tankrange"]["logging"]:
					LOG_NOTE("Situational Awareness Bonus: ", 1.0 + ( 0.0003 * data["skill"]["radioman_finder"] ))

		# Check for Binoculars
		binoculars = self.__isOptionalEquipped("stereoscope")
		if xvm_conf["tankrange"]["logging"] and binoculars:
			LOG_NOTE("Binoculars Found")

		# Check for Coated Optics
		coated_optics = self.__isOptionalEquipped("coatedOptics")
		if xvm_conf["tankrange"]["logging"] and coated_optics:
			LOG_NOTE("Coated Optics Found")

		# Calculate final value
		view_distance = ((view_distance / 0.875) * (0.00375* commander_skill + 0.5)) * other_bonus

		if xvm_conf["tankrange"]["logging"]:
			LOG_NOTE("Other Bonus:", other_bonus)
			LOG_NOTE("Final View Range: ", view_distance)

		# Add binocular Circles
		if xvm_conf["tankrange"]["binocular_circle"]["enabled"] and binoculars:
			xvm_conf["circles"]["special"].append({ tank_name: { "$ref": { "path": "circle_binocular" }, "distance": view_distance * 1.25 } })

		# Add standard Circles
		if coated_optics == True:
			view_distance = min(view_distance * 1.1, 500)

		if xvm_conf["tankrange"]["view_circle"]["enabled"]:
			xvm_conf["circles"]["special"].append({ tank_name: { "$ref": { "path": "circle_view" }, "distance": view_distance } })

		# Add Artillery Range
		if xvm_conf["tankrange"]["artillery"]["circle"]["enabled"] and "SPG" in self.__vehicle.descriptor.type.tags:
			artillery_range = 0
			for shell in self.__vehicle.descriptor.gun["shots"]:
				artillery_range = max(artillery_range, round(math.pow(shell["speed"],2) / shell["gravity"]))

			if xvm_conf["tankrange"]["logging"]:
				LOG_NOTE("Calculated Firing Range:", artillery_range)

			xvm_conf["circles"]["special"].append({ tank_name: { "$ref": { "path": "circle_binocular" }, "distance": artillery_range } })

		# Write result
		f = codecs.open(xvm_configuration_file, 'w', '"utf-8-sig"')
		f.write(unicode(json.dumps(xvm_conf, ensure_ascii=False, indent=2, sort_keys=True)))
		f.close()

		return

	@process
	def __updateCrew(self):
		from gui.Scaleform.utils.requesters import Requester
		self.__crew.clear()

		barracks = yield Requester('tankman').getFromInventory()
		for tankman in barracks:
			for crew_id in self.__vehicle.crew:
				if crew_id == tankman.inventoryId:
					crew_member = { "level": tankman.descriptor.roleLevel, "skill": {} }

					skills = []
					for skill_name in tankman.descriptor.skills:
						skills.append({ "name": skill_name, "level": 100 })

					if len(skills) != 0:
						skills[-1]["level"] = tankman.descriptor.lastSkillLevel

					for skill in skills:
						crew_member["skill"][skill["name"]] = skill["level"]

					self.__crew[tankman.descriptor.role] = crew_member

	def __isOptionalEquipped(self, optional_name):
		for item in self.__vehicle.descriptor.optionalDevices:
			if item is not None and optional_name in item.name:
				return True
		return False

	def __isConsumableEquipped(self, consumable_name):
		from gui.Scaleform.utils.requesters import VehicleItemsRequester

		for item in VehicleItemsRequester([self.__vehicle]).getItems(['equipment']):
			if item.descriptor is not None:
				for mounted in self.__vehicle.equipments:
					if item.compactDescr == mounted:
						if consumable_name in item.descriptor.name:
							return True
		return False

	def __changeDone(self):
		self.__changeCallbackID = None
		player = BigWorld.player()
		if player and hasattr(player, 'isPlayer') and player.isPlayer:
			self.onChanged()
		Waiting.hide('updateCurrentVehicle')
		return

	def __findCurrent(self, inventoryId, vehicles):
		for vehicle in vehicles:
			if vehicle.inventoryId == inventoryId:
				return vehicle

		vehicles.sort()
		if len(vehicles):
			return vehicles[0]
		else:
			return None

	def update(self):
		if self.firstTimeInitialized:
			self.__request(self.__vehicle.inventoryId if self.__vehicle else None)
		return

	@async
	@process
	def getFromServer(self, callback):
		currentId = AccountSettings.getFavorites('current')
		from gui.Scaleform.utils.requesters import Requester
		vehiclesList = yield Requester('vehicle').getFromInventory()
		prebattle = AccountPrebattle.get()
		if prebattle is not None:
			for rId, roster in prebattle.rosters.iteritems():
				if BigWorld.player().id in roster:
					vehCompDescr = roster[BigWorld.player().id].get('vehCompDescr')
					if len(vehCompDescr):
						vehDescr = vehicles.VehicleDescr(compactDescr=vehCompDescr)
						for v in vehiclesList:
							if v.descriptor.type.id == vehDescr.type.id:
								currentId = v.inventoryId
								break

		self.__vehicle = self.__findCurrent(currentId, vehiclesList)
		self.item = yield self.__requestVehicleItem(currentId)
		self.onChanged()
		self.firstTimeInitialized = True
		callback(True)
		return

	@async
	@process
	def __requestVehicleItem(self, invID, callback):
		from gui.Scaleform.utils.requesters import ItemsRequester
		ir = yield ItemsRequester().request()
		callback(ir.getFromInventory(vehicles._VEHICLE).inventoryMap().get(invID, None))
		return

	def getParams(self):
		from gui.Scaleform.utils import ItemsParameters
		data = list()
		if self.isPresent():
			params = ItemsParameters.g_instance.getParameters(g_currentVehicle.vehicle)
			if params is not None:
				for p in params:
					data.append(p[0])
					data.append(p[1])

		return data


g_currentVehicle = _CurrentVehicle()
